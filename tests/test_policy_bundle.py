import json
from pathlib import Path

import pytest

from eagle_eye.policy import PolicyBundleError, evaluate_policy, load_policy_bundle, verify_policy_decision

POLICY = Path(__file__).resolve().parents[1] / "policies/action-governance-v1.json"
POLICY_SHA256 = "1a47ce736ef27e60fa3aea3d2abcb96aa4e1eb8b22f492c335502d0dc9f75f1f"


def test_hash_pinned_policy_bundle_loads():
    bundle = load_policy_bundle(POLICY, expected_sha256=POLICY_SHA256)
    assert bundle["policy_id"] == "eagle-eye-action-governance/1.0"
    assert bundle["release"] == "2026-07-12.1"
    assert bundle["bundle_sha256"] == POLICY_SHA256


def test_tampered_policy_bundle_is_rejected(tmp_path):
    tampered = json.loads(POLICY.read_text())
    tampered["allowed_mode"] = "LIVE"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(tampered, indent=2))
    with pytest.raises(PolicyBundleError, match="hash"):
        load_policy_bundle(path, expected_sha256=POLICY_SHA256)


def test_policy_downgrade_or_unknown_schema_is_rejected(tmp_path):
    downgraded = json.loads(POLICY.read_text())
    downgraded["policy_id"] = "eagle-eye-action-governance/0.9"
    path = tmp_path / "downgraded.json"
    path.write_text(json.dumps(downgraded))
    with pytest.raises(PolicyBundleError, match="policy id"):
        load_policy_bundle(path, expected_sha256=None)


def test_decision_binds_exact_bundle_release_and_hash():
    bundle = load_policy_bundle(POLICY, expected_sha256=POLICY_SHA256)
    decision = evaluate_policy(
        operation="approve_action",
        principal={"id": "approver", "tenant_id": "tenant-a", "roles": ["approver"], "session_id": "s1"},
        resource={
            "action_id": "action-1",
            "tenant_id": "tenant-a",
            "mode": "FIXTURE",
            "status": "awaiting_independent_approval",
            "requester_id": "analyst",
            "evidence_ids": ["SRC-1"],
        },
        expected_action_id="action-1",
        bundle=bundle,
    )
    assert decision["effect"] == "ALLOW"
    assert decision["policy_release"] == "2026-07-12.1"
    assert decision["policy_bundle_sha256"] == POLICY_SHA256


def test_reverification_rejects_bundle_body_tampered_under_original_hash():
    bundle = load_policy_bundle(POLICY, expected_sha256=POLICY_SHA256)
    principal = {"id": "approver", "tenant_id": "tenant-a", "roles": ["approver"], "session_id": "s1"}
    resource = {
        "action_id": "action-1",
        "tenant_id": "tenant-a",
        "mode": "FIXTURE",
        "status": "awaiting_independent_approval",
        "requester_id": "analyst",
        "evidence_ids": ["SRC-1"],
    }
    decision = evaluate_policy(
        operation="approve_action",
        principal=principal,
        resource=resource,
        expected_action_id="action-1",
        bundle=bundle,
    )
    tampered = json.loads(json.dumps(bundle))
    tampered["operations"]["approve_action"]["required_role"] = "viewer"
    assert not verify_policy_decision(
        decision,
        operation="approve_action",
        principal_id="approver",
        session_id="s1",
        tenant_id="tenant-a",
        resource=resource,
        bundle=tampered,
    )
