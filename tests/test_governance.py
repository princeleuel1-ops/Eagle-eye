import pytest

from eagle_eye.governance import ApprovalError, approve_action, request_action


def _action():
    return {
        "id": "action-1",
        "tenant_id": "tenant-a",
        "status": "pending_approval",
        "mode": "FIXTURE",
        "evidence_ids": ["SRC-1"],
    }


def test_dual_control_approval_creates_shadow_only_receipt():
    request = request_action(
        _action(),
        principal={"id": "analyst-1", "tenant_id": "tenant-a", "roles": ["analyst"]},
    )
    result = approve_action(
        request,
        principal={"id": "approver-1", "tenant_id": "tenant-a", "roles": ["approver"]},
    )
    assert result["action_status"] == "approved_shadow"
    assert result["requester_id"] == "analyst-1"
    assert result["approver_id"] == "approver-1"
    assert result["tenant_id"] == "tenant-a"
    assert result["external_execution"] is False
    assert result["evidence_ids"] == ["SRC-1"]
    assert result["receipt_id"].startswith("approval-")


def test_self_approval_is_rejected():
    request = request_action(
        _action(),
        principal={"id": "same-user", "tenant_id": "tenant-a", "roles": ["analyst", "approver"]},
    )
    with pytest.raises(ApprovalError, match="dual control"):
        approve_action(
            request,
            principal={"id": "same-user", "tenant_id": "tenant-a", "roles": ["approver"]},
        )


def test_cross_tenant_approval_is_rejected():
    request = request_action(
        _action(),
        principal={"id": "analyst-1", "tenant_id": "tenant-a", "roles": ["analyst"]},
    )
    with pytest.raises(ApprovalError, match="tenant"):
        approve_action(
            request,
            principal={"id": "approver-b", "tenant_id": "tenant-b", "roles": ["approver"]},
        )


def test_non_approver_role_is_rejected():
    request = request_action(
        _action(),
        principal={"id": "analyst-1", "tenant_id": "tenant-a", "roles": ["analyst"]},
    )
    with pytest.raises(ApprovalError, match="approver role"):
        approve_action(
            request,
            principal={"id": "viewer-1", "tenant_id": "tenant-a", "roles": ["viewer"]},
        )
