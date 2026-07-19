import pytest

from eagle_eye.policy import evaluate_policy, verify_policy_decision


def _principal(role="approver", tenant="tenant-a", subject="approver-1"):
    return {"id": subject, "tenant_id": tenant, "roles": [role], "session_id": f"session-{subject}"}


def _resource(**changes):
    resource = {
        "action_id": "action-1",
        "tenant_id": "tenant-a",
        "mode": "FIXTURE",
        "status": "awaiting_independent_approval",
        "requester_id": "analyst-1",
        "evidence_ids": ["SRC-1"],
    }
    resource.update(changes)
    return resource


def test_valid_resource_scoped_approval_is_allowed():
    decision = evaluate_policy(
        operation="approve_action",
        principal=_principal(),
        resource=_resource(),
        expected_action_id="action-1",
    )
    assert decision["effect"] == "ALLOW"
    assert decision["reasons"] == []
    assert decision["policy_id"] == "eagle-eye-action-governance/1.0"
    assert decision["receipt_id"].startswith("policy-")


@pytest.mark.parametrize(
    ("principal", "resource", "expected_action_id", "reason"),
    [
        (_principal(role="viewer"), _resource(), "action-1", "missing_required_role"),
        (_principal(tenant="tenant-b"), _resource(), "action-1", "tenant_mismatch"),
        (_principal(subject="analyst-1"), _resource(), "action-1", "separation_of_duties_violation"),
        (_principal(), _resource(evidence_ids=[]), "action-1", "missing_evidence"),
        (_principal(), _resource(status="approved_shadow"), "action-1", "invalid_resource_state"),
        (_principal(), _resource(mode="LIVE"), "action-1", "live_execution_not_authorized"),
        (_principal(), _resource(action_id="action-2"), "action-1", "resource_mismatch"),
    ],
)
def test_policy_denies_invalid_approval(principal, resource, expected_action_id, reason):
    decision = evaluate_policy(
        operation="approve_action",
        principal=principal,
        resource=resource,
        expected_action_id=expected_action_id,
    )
    assert decision["effect"] == "DENY"
    assert reason in decision["reasons"]
    assert decision["receipt_id"].startswith("policy-")


def test_unknown_operation_fails_closed():
    decision = evaluate_policy(
        operation="delete_everything",
        principal=_principal(),
        resource=_resource(),
        expected_action_id="action-1",
    )
    assert decision["effect"] == "DENY"
    assert decision["reasons"] == ["unsupported_operation"]


def test_request_policy_requires_analyst_pending_action_and_evidence():
    decision = evaluate_policy(
        operation="request_action",
        principal=_principal(role="analyst", subject="analyst-1"),
        resource=_resource(status="pending_approval", requester_id=None),
        expected_action_id="action-1",
    )
    assert decision["effect"] == "ALLOW"


def test_policy_receipt_reverification_binds_exact_resource():
    principal = _principal()
    resource = _resource()
    decision = evaluate_policy(operation="approve_action", principal=principal, resource=resource, expected_action_id="action-1")
    assert verify_policy_decision(
        decision,
        operation="approve_action",
        principal_id=principal["id"],
        session_id=principal["session_id"],
        tenant_id="tenant-a",
        resource=resource,
    )
    changed = {**resource, "evidence_ids": ["SRC-OTHER"]}
    assert not verify_policy_decision(
        decision,
        operation="approve_action",
        principal_id=principal["id"],
        session_id=principal["session_id"],
        tenant_id="tenant-a",
        resource=changed,
    )


def test_tampered_allow_receipt_fails_reverification():
    principal = _principal()
    resource = _resource()
    decision = evaluate_policy(operation="approve_action", principal=principal, resource=resource, expected_action_id="action-1")
    decision["principal_id"] = "attacker"
    assert not verify_policy_decision(
        decision,
        operation="approve_action",
        principal_id="attacker",
        session_id=principal["session_id"],
        tenant_id="tenant-a",
        resource=resource,
    )
