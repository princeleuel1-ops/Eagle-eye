import base64
import copy

import pytest

from eagle_eye.signed_chain import SignedChain, verify_chain
from eagle_eye.signing import generate_demo_keypair


@pytest.fixture()
def chain():
    private_key, public_key = generate_demo_keypair()
    chain = SignedChain(tenant_id="tenant-demo", run_id="run-1", chain_id="test",
                        private_key=private_key, public_key=public_key)
    for index in range(4):
        chain.append({"kind": "event", "index": index})
    registry = {"trusted_signers": [{"key_id": chain.signer_key_id,
                                     "public_key_pem": public_key.decode()}]}
    return chain, registry


def test_valid_chain_verifies(chain):
    c, registry = chain
    result = verify_chain(c.rows, c.anchor(), registry, expected_tenant="tenant-demo")
    assert result["verified"] is True and result["length"] == 4


def test_rewritten_and_rehashed_row_rejected(chain):
    """The audits core attack: rewrite a row AND recompute its hash; without the
    signer key the signature cannot be regenerated -> rejected."""
    c, registry = chain
    rows = copy.deepcopy(c.rows)
    rows[1]["body"]["index"] = 999
    from eagle_eye.prior_registry import canonical_bytes, sha256_hex
    body = {k: v for k, v in rows[1].items() if k not in ("row_hash", "signature_b64", "signer_key_id")}
    rows[1]["row_hash"] = sha256_hex(canonical_bytes(body))  # attacker rehashes
    # relink the rest of the chain like a full rewrite would
    head = rows[1]["row_hash"]
    for row in rows[2:]:
        row["previous_hash"] = head
        rebody = {k: v for k, v in row.items() if k not in ("row_hash", "signature_b64", "signer_key_id")}
        row["row_hash"] = sha256_hex(canonical_bytes(rebody))
        head = row["row_hash"]
    anchor = dict(c.anchor())
    result = verify_chain(rows, anchor, registry, expected_tenant="tenant-demo")
    assert result["verified"] is False  # anchor head mismatch or forged signature
    # even with a forged anchor head the signatures fail
    anchor["head"] = head
    result = verify_chain(rows, anchor, registry, expected_tenant="tenant-demo")
    assert result["verified"] is False
    assert "forged" in result["reason"] or "anchor" in result["reason"]


def test_tail_truncation_rejected(chain):
    c, registry = chain
    result = verify_chain(c.rows[:-1], c.anchor(), registry, expected_tenant="tenant-demo")
    assert result["verified"] is False
    assert "anchor" in result["reason"] or "length" in result["reason"]


def test_reordered_events_rejected(chain):
    c, registry = chain
    rows = copy.deepcopy(c.rows)
    rows[1], rows[2] = rows[2], rows[1]
    result = verify_chain(rows, c.anchor(), registry, expected_tenant="tenant-demo")
    assert result["verified"] is False


def test_signer_substitution_rejected(chain):
    c, registry = chain
    attacker_private, attacker_public = generate_demo_keypair()
    attacker = SignedChain(tenant_id="tenant-demo", run_id="run-1", chain_id="test",
                           private_key=attacker_private, public_key=attacker_public)
    for row in c.rows:
        attacker.append(row["body"])
    # attacker presents their own chain + anchor, but they are not in the registry
    result = verify_chain(attacker.rows, attacker.anchor(), registry, expected_tenant="tenant-demo")
    assert result["verified"] is False
    assert result["reason"] == "unknown signer"


def test_wrong_tenant_rejected(chain):
    c, registry = chain
    result = verify_chain(c.rows, c.anchor(), registry, expected_tenant="tenant-mallory")
    assert result["verified"] is False
    assert result["reason"] == "wrong tenant"


def test_forged_anchor_signature_rejected(chain):
    c, registry = chain
    anchor = dict(c.anchor())
    anchor["length"] = 3
    result = verify_chain(c.rows[:3], anchor, registry, expected_tenant="tenant-demo")
    assert result["verified"] is False
    assert "forged anchor" in result["reason"] or "anchor" in result["reason"]


def test_chain_id_binding_and_pinning(chain):
    """V5 hardening: the anchor's signed chain_id is bound to every row, and a
    caller may pin the expected chain_id (cross-chain confusion defense)."""
    c, registry = chain
    # valid when pinned to the true chain_id
    ok = verify_chain(c.rows, c.anchor(), registry, expected_tenant="tenant-demo",
                      expected_chain_id="test")
    assert ok["verified"] is True and ok["chain_id"] == "test"
    # rejected when the caller expects a different chain
    bad = verify_chain(c.rows, c.anchor(), registry, expected_tenant="tenant-demo",
                       expected_chain_id="some-other-chain")
    assert bad["verified"] is False and "chain_id mismatch" in bad["reason"]


def test_cross_chain_presentation_rejected_by_pinning():
    """The real key-reuse confusion threat: ONE signer key signs two chains;
    an attacker presents the whole 'evaluator-access' chain (internally valid)
    where the caller expects 'lineage'. Without pinning it would verify (the
    hazard); WITH expected_chain_id pinning it is rejected. This is why the
    pin exists."""
    private_key, public_key = generate_demo_keypair()
    evaluator = SignedChain(tenant_id="tenant-demo", run_id="run-1",
                            chain_id="evaluator-access",
                            private_key=private_key, public_key=public_key)
    evaluator.append({"kind": "promotion_look_charge", "look_index": 1})
    reg = {"trusted_signers": [{"key_id": evaluator.signer_key_id,
                                "public_key_pem": public_key.decode()}]}
    # unpinned: internally valid (this is exactly the hazard being closed)
    unpinned = verify_chain(evaluator.rows, evaluator.anchor(), reg,
                            expected_tenant="tenant-demo")
    assert unpinned["verified"] is True and unpinned["chain_id"] == "evaluator-access"
    # pinned to the expected slot: rejected
    pinned = verify_chain(evaluator.rows, evaluator.anchor(), reg,
                          expected_tenant="tenant-demo", expected_chain_id="lineage")
    assert pinned["verified"] is False and "chain_id mismatch" in pinned["reason"]


def test_spliced_foreign_row_rejected(chain):
    """Hand-splicing a row with a foreign chain_id (without re-signing) is
    rejected — by row-hash and/or the chain_id binding; either is correct."""
    c, registry = chain
    rows = copy.deepcopy(c.rows)
    rows[2]["chain_id"] = "evaluator-access"
    result = verify_chain(rows, c.anchor(), registry, expected_tenant="tenant-demo")
    assert result["verified"] is False
    assert "chain_id confusion" in result["reason"] or "row hash mismatch" in result["reason"]


def test_malformed_signer_pem_fails_closed(chain):
    """Garbage PEM must fail closed (verified:False), not raise."""
    c, _ = chain
    bad_registry = {"trusted_signers": [{"key_id": c.signer_key_id,
                                         "public_key_pem": "-----BEGIN PUBLIC KEY-----\nnonsense\n-----END PUBLIC KEY-----"}]}
    result = verify_chain(c.rows, c.anchor(), bad_registry, expected_tenant="tenant-demo")
    assert result["verified"] is False
    assert "malformed" in result["reason"] or "mismatch" in result["reason"]
