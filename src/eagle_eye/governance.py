from __future__ import annotations

import hashlib
import json
from typing import Any

from .policy import evaluate_policy


class ApprovalError(ValueError):
    """Raised when an action violates approval invariants."""


def _receipt_id(prefix: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"{prefix}-{hashlib.sha256(canonical).hexdigest()[:12]}"


def _validate_principal(principal: dict[str, Any]) -> None:
    if not principal.get("id") or not principal.get("tenant_id"):
        raise ApprovalError("principal id and tenant are required")
    if not isinstance(principal.get("roles"), list):
        raise ApprovalError("principal roles are required")


def request_action(
    action: dict[str, Any],
    *,
    principal: dict[str, Any],
    policy_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_principal(principal)
    if action.get("status") != "pending_approval":
        raise ApprovalError("action must be pending approval")
    if action.get("tenant_id") != principal["tenant_id"]:
        raise ApprovalError("requester tenant does not match action tenant")
    if "analyst" not in principal["roles"]:
        raise ApprovalError("analyst role is required to request action")
    policy = evaluate_policy(
        operation="request_action",
        principal=principal,
        resource={
            "action_id": action["id"],
            "tenant_id": action["tenant_id"],
            "mode": action.get("mode", "FIXTURE"),
            "status": action["status"],
            "requester_id": None,
            "evidence_ids": action.get("evidence_ids", []),
        },
        expected_action_id=action["id"],
        bundle=policy_bundle,
    )
    if policy["effect"] != "ALLOW":
        raise ApprovalError(f"policy denied action request: {','.join(policy['reasons'])}")
    request = {
        "action_id": action["id"],
        "tenant_id": action["tenant_id"],
        "mode": action.get("mode", "FIXTURE"),
        "requester_id": principal["id"],
        "status": "awaiting_independent_approval",
        "evidence_ids": sorted(set(action.get("evidence_ids", []))),
        "policy_decision": policy,
    }
    request["request_id"] = _receipt_id("request", request)
    return request


def approve_action(
    request: dict[str, Any],
    *,
    principal: dict[str, Any],
    policy_bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_principal(principal)
    if request.get("status") != "awaiting_independent_approval":
        raise ApprovalError("request is not awaiting approval")
    if principal["tenant_id"] != request.get("tenant_id"):
        raise ApprovalError("approver tenant does not match request tenant")
    if "approver" not in principal["roles"]:
        raise ApprovalError("approver role is required")
    if principal["id"] == request.get("requester_id"):
        raise ApprovalError("dual control requires a different approver")
    policy = evaluate_policy(
        operation="approve_action",
        principal=principal,
        resource={
            "action_id": request["action_id"],
            "tenant_id": request["tenant_id"],
            "mode": request.get("mode", "FIXTURE"),
            "status": request["status"],
            "requester_id": request["requester_id"],
            "evidence_ids": request.get("evidence_ids", []),
        },
        expected_action_id=request["action_id"],
        bundle=policy_bundle,
    )
    if policy["effect"] != "ALLOW":
        raise ApprovalError(f"policy denied approval: {','.join(policy['reasons'])}")
    is_fixture = request.get("mode") == "FIXTURE"
    receipt = {
        "request_id": request["request_id"],
        "action_id": request["action_id"],
        "tenant_id": request["tenant_id"],
        "requester_id": request["requester_id"],
        "approver_id": principal["id"],
        "action_status": "approved_shadow" if is_fixture else "approved_pending_execution",
        "external_execution": False,
        "evidence_ids": request.get("evidence_ids", []),
        "dual_control_verified": True,
        "tenant_verified": True,
        "request_policy_receipt_id": request["policy_decision"]["receipt_id"],
        "policy_decision": policy,
    }
    receipt["receipt_id"] = _receipt_id("approval", receipt)
    return receipt
