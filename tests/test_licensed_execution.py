"""V12: arming, per-action licenses, proof chain, reversal."""
import time
import pytest
from eagle_eye.licensed_execution import (
    ARMED_TEST_FIXTURE, UNARMED, ExecutionRefused, LicensedExecutor,
    LocalOutboxAdapter, issue_action_token, sign_arming_config, verify_arming)
from eagle_eye.pilot.kms import EphemeralKeyProvider
from eagle_eye.prior_registry import canonical_bytes, sha256_hex
from eagle_eye.signing import generate_demo_keypair, key_id


def _armed(tmp_path, max_actions=3):
    priv, pub = generate_demo_keypair()
    pinned = {key_id(pub): pub}
    cfg = sign_arming_config({"spec": "eagle-eye-execution-arming/1.0",
        "arming_class": "test_fixture", "tenant_id": "t", "action_classes": ["notify"],
        "max_actions": max_actions, "authorized_by": [{"sub": "a"}, {"sub": "b"}],
        "valid_from_epoch": time.time() - 1, "valid_until_epoch": time.time() + 600},
        priv, pub)
    v = verify_arming(cfg, trusted_authority_keys=pinned)
    ex = LicensedExecutor(verification=v, adapter=LocalOutboxAdapter(tmp_path / "o.jsonl"),
                          trusted_authority_keys=pinned, signer=EphemeralKeyProvider())
    return priv, pub, pinned, v, ex


def _token(priv, pub, v, action_id="a1", ev=None):
    ev = ev or sha256_hex(canonical_bytes({"e": 1}))
    return ev, issue_action_token({"spec": "eagle-eye-licensed-execution/1.0",
        "action_id": action_id, "action_class": "notify", "evidence_digest": ev,
        "approval_receipt_id": "appr-1", "arming_config_sha256": v["config_sha256"],
        "issued_at_epoch": time.time()}, priv, pub)


def test_unarmed_default_and_tamper():
    _, pub = generate_demo_keypair()
    assert verify_arming(None, trusted_authority_keys={key_id(pub): pub})["arm_state"] == UNARMED
    priv2, pub2 = generate_demo_keypair()
    cfg = sign_arming_config({"spec": "eagle-eye-execution-arming/1.0",
        "arming_class": "test_fixture", "tenant_id": "t", "action_classes": ["notify"],
        "max_actions": 1, "authorized_by": [{"sub": "a"}, {"sub": "b"}],
        "valid_from_epoch": 0, "valid_until_epoch": time.time() + 60}, priv2, pub2)
    cfg["max_actions"] = 999
    assert verify_arming(cfg, trusted_authority_keys={key_id(pub2): pub2})["arm_state"] == UNARMED


def test_full_action_chain_budget_and_reversal(tmp_path):
    priv, pub, pinned, v, ex = _armed(tmp_path, max_actions=1)
    assert v["arm_state"] == ARMED_TEST_FIXTURE
    ev, tok = _token(priv, pub, v)
    r = ex.execute(action_id="a1", action_class="notify", payload={"m": 1},
                   principal={"sub": "a"}, evidence_digest=ev,
                   approval_receipt_id="appr-1", token=tok)
    assert r["receipt_sha256"] and r["receipt_signature_b64"] and r["outcome"]["delivered"]
    assert ex.reverse(r)["reverses_receipt_sha256"] == r["receipt_sha256"]
    ev2, tok2 = _token(priv, pub, v, action_id="a2")
    with pytest.raises(ExecutionRefused, match="budget"):
        ex.execute(action_id="a2", action_class="notify", payload={},
                   principal={}, evidence_digest=ev2,
                   approval_receipt_id="appr-1", token=tok2)


def test_license_single_use_binding_and_expiry(tmp_path):
    priv, pub, pinned, v, ex = _armed(tmp_path)
    ev, tok = _token(priv, pub, v)
    ex.execute(action_id="a1", action_class="notify", payload={}, principal={},
               evidence_digest=ev, approval_receipt_id="appr-1", token=tok)
    with pytest.raises(ExecutionRefused, match="single-use"):
        ex.execute(action_id="a1", action_class="notify", payload={}, principal={},
                   evidence_digest=ev, approval_receipt_id="appr-1", token=tok)
    ev2, tok2 = _token(priv, pub, v, action_id="aX")
    with pytest.raises(ExecutionRefused, match="bind"):
        ex.execute(action_id="aY", action_class="notify", payload={}, principal={},
                   evidence_digest=ev2, approval_receipt_id="appr-1", token=tok2)
    old = issue_action_token({"spec": "eagle-eye-licensed-execution/1.0",
        "action_id": "a3", "action_class": "notify", "evidence_digest": ev2,
        "approval_receipt_id": "appr-1", "arming_config_sha256": v["config_sha256"],
        "issued_at_epoch": time.time() - 9999}, priv, pub)
    with pytest.raises(ExecutionRefused, match="expired"):
        ex.execute(action_id="a3", action_class="notify", payload={}, principal={},
                   evidence_digest=ev2, approval_receipt_id="appr-1", token=old)


def test_production_arming_requires_custody():
    priv, pub = generate_demo_keypair()
    pinned = {key_id(pub): pub}
    cfg = sign_arming_config({"spec": "eagle-eye-execution-arming/1.0",
        "arming_class": "production", "tenant_id": "t", "action_classes": ["notify"],
        "max_actions": 1, "authorized_by": [{"sub": "a"}, {"sub": "b"}],
        "valid_from_epoch": 0, "valid_until_epoch": time.time() + 60}, priv, pub)
    r = verify_arming(cfg, trusted_authority_keys=pinned, custody_descriptor=None)
    assert r["arm_state"] == UNARMED and any("custody" in x for x in r["reasons"])
