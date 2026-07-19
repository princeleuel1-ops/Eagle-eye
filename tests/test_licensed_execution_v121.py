"""V12.1 hardening: three-way authority independence, separate approval-
authority authorization, and durable SQLite single-use reservation."""
import time
import pytest
from eagle_eye.licensed_execution import (
    ARMED_TEST_FIXTURE, AUTHORIZATION_SPEC, LICENSE_SPEC_V11, DurableReservationLedger,
    ExecutionRefused, HardenedLicensedExecutor, LocalOutboxAdapter, issue_action_token,
    sign_action_authorization, sign_arming_config, verify_arming)
from eagle_eye.pilot.kms import EphemeralKeyProvider
from eagle_eye.prior_registry import canonical_bytes, sha256_hex
from eagle_eye.signing import generate_demo_keypair, key_id


def _kp():
    p, u = generate_demo_keypair()
    return p, u, key_id(u)


def _rig(tmp_path, same_key_for=None):
    arm_priv, arm_pub, arm_id = _kp()
    app_priv, app_pub, app_id = _kp()
    v = verify_arming(sign_arming_config({"spec": "eagle-eye-execution-arming/1.0",
        "arming_class": "test_fixture", "tenant_id": "t", "action_classes": ["notify"],
        "max_actions": 5, "authorized_by": [{"sub": "a"}, {"sub": "b"}],
        "valid_from_epoch": time.time() - 1, "valid_until_epoch": time.time() + 600},
        arm_priv, arm_pub), trusted_authority_keys={arm_id: arm_pub})
    signer = EphemeralKeyProvider()
    ledger = DurableReservationLedger(tmp_path / "res.sqlite3")
    ex = HardenedLicensedExecutor(verification=v, adapter=LocalOutboxAdapter(tmp_path / "o.jsonl"),
        trusted_authority_keys={arm_id: arm_pub}, approval_authority_keys={app_id: app_pub},
        reservation_ledger=ledger, signer=signer)
    return arm_priv, arm_pub, app_priv, app_pub, v, ex, ledger


def _docs(arm_priv, arm_pub, app_priv, app_pub, v, action_id="a1"):
    ev = sha256_hex(canonical_bytes({"e": action_id}))
    authz = sign_action_authorization({"spec": AUTHORIZATION_SPEC, "action_id": action_id,
        "action_class": "notify", "requester_id": "req-1", "approver_id": "app-1",
        "evidence_digest": ev, "arming_config_sha256": v["config_sha256"],
        "issued_at_epoch": time.time()}, app_priv, app_pub)
    tok = issue_action_token({"spec": LICENSE_SPEC_V11, "action_id": action_id,
        "action_class": "notify", "evidence_digest": ev,
        "approval_receipt_id": authz["authorization_sha256"],
        "arming_config_sha256": v["config_sha256"], "issued_at_epoch": time.time()},
        arm_priv, arm_pub)
    return ev, authz, tok


def test_full_hardened_action_and_proof_chain(tmp_path):
    arm_priv, arm_pub, app_priv, app_pub, v, ex, _ = _rig(tmp_path)
    ev, authz, tok = _docs(arm_priv, arm_pub, app_priv, app_pub, v)
    r = ex.execute(action_id="a1", action_class="notify", payload={"m": 1},
                   principal={"sub": "req-1"}, evidence_digest=ev,
                   authorization=authz, token=tok)
    assert r["spec"] == LICENSE_SPEC_V11 and r["outcome"]["delivered"]
    assert r["requester_id"] != r["approver_id"]
    assert r["authorization_sha256"] and r["receipt_signature_b64"]


def test_three_way_independence_enforced(tmp_path):
    arm_priv, arm_pub, arm_id = _kp()
    # reuse arming key as approval key -> must refuse construction
    v = verify_arming(sign_arming_config({"spec": "eagle-eye-execution-arming/1.0",
        "arming_class": "test_fixture", "tenant_id": "t", "action_classes": ["notify"],
        "max_actions": 1, "authorized_by": [{"sub": "a"}, {"sub": "b"}],
        "valid_from_epoch": 0, "valid_until_epoch": time.time() + 60},
        arm_priv, arm_pub), trusted_authority_keys={arm_id: arm_pub})
    with pytest.raises(ExecutionRefused, match="independent"):
        HardenedLicensedExecutor(verification=v, adapter=LocalOutboxAdapter(tmp_path / "o"),
            trusted_authority_keys={arm_id: arm_pub}, approval_authority_keys={arm_id: arm_pub},
            reservation_ledger=DurableReservationLedger(tmp_path / "r.db"),
            signer=EphemeralKeyProvider())


def test_requester_equals_approver_refused(tmp_path):
    arm_priv, arm_pub, app_priv, app_pub, v, ex, _ = _rig(tmp_path)
    ev = sha256_hex(canonical_bytes({"e": "x"}))
    with pytest.raises(ExecutionRefused, match="differ"):
        sign_action_authorization({"spec": AUTHORIZATION_SPEC, "action_id": "a1",
            "action_class": "notify", "requester_id": "same", "approver_id": "same",
            "evidence_digest": ev, "arming_config_sha256": v["config_sha256"],
            "issued_at_epoch": time.time()}, app_priv, app_pub)


def test_durable_single_use_survives_new_executor(tmp_path):
    arm_priv, arm_pub, app_priv, app_pub, v, ex, ledger = _rig(tmp_path)
    ev, authz, tok = _docs(arm_priv, arm_pub, app_priv, app_pub, v)
    ex.execute(action_id="a1", action_class="notify", payload={}, principal={},
               evidence_digest=ev, authorization=authz, token=tok)
    # brand-new executor, SAME durable ledger -> replay still refused
    ex2 = HardenedLicensedExecutor(verification=v, adapter=LocalOutboxAdapter(tmp_path / "o2"),
        trusted_authority_keys=ex.trusted, approval_authority_keys=ex.approvals,
        reservation_ledger=DurableReservationLedger(ledger.path), signer=EphemeralKeyProvider())
    with pytest.raises(ExecutionRefused, match="already spent"):
        ex2.execute(action_id="a1", action_class="notify", payload={}, principal={},
                    evidence_digest=ev, authorization=authz, token=tok)


def test_unpinned_approval_authority_refused(tmp_path):
    arm_priv, arm_pub, app_priv, app_pub, v, ex, _ = _rig(tmp_path)
    other_priv, other_pub, _ = _kp()  # not pinned as approval authority
    ev = sha256_hex(canonical_bytes({"e": "a1"}))
    authz = sign_action_authorization({"spec": AUTHORIZATION_SPEC, "action_id": "a1",
        "action_class": "notify", "requester_id": "req-1", "approver_id": "app-1",
        "evidence_digest": ev, "arming_config_sha256": v["config_sha256"],
        "issued_at_epoch": time.time()}, other_priv, other_pub)
    tok = issue_action_token({"spec": LICENSE_SPEC_V11, "action_id": "a1",
        "action_class": "notify", "evidence_digest": ev,
        "approval_receipt_id": authz["authorization_sha256"],
        "arming_config_sha256": v["config_sha256"], "issued_at_epoch": time.time()},
        arm_priv, arm_pub)
    with pytest.raises(ExecutionRefused, match="approval authority"):
        ex.execute(action_id="a1", action_class="notify", payload={}, principal={},
                   evidence_digest=ev, authorization=authz, token=tok)


def test_binding_mismatch_refused(tmp_path):
    arm_priv, arm_pub, app_priv, app_pub, v, ex, _ = _rig(tmp_path)
    ev, authz, tok = _docs(arm_priv, arm_pub, app_priv, app_pub, v, action_id="a1")
    with pytest.raises(ExecutionRefused, match="bindings do not agree"):
        ex.execute(action_id="aZ", action_class="notify", payload={}, principal={},
                   evidence_digest=ev, authorization=authz, token=tok)
