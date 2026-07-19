from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

POLICY_ID = "eagle-eye-action-governance/1.0"
REQUIRED_BUNDLE_KEYS = {"policy_id", "release", "default_effect", "allowed_mode", "operations"}
REQUIRED_OPERATIONS = {"request_action", "approve_action"}
REQUIRED_RULE_KEYS = {"required_role", "required_state", "requires_evidence", "requires_separation_of_duties"}


class PolicyBundleError(ValueError):
    """Raised when a policy release is malformed or not the pinned release."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


_DEFAULT_BODY: dict[str, Any] = {
    "policy_id": POLICY_ID,
    "release": "builtin-test-default",
    "default_effect": "DENY",
    "allowed_mode": "FIXTURE",
    "operations": {
        "request_action": {
            "required_role": "analyst",
            "required_state": "pending_approval",
            "requires_evidence": True,
            "requires_separation_of_duties": False,
        },
        "approve_action": {
            "required_role": "approver",
            "required_state": "awaiting_independent_approval",
            "requires_evidence": True,
            "requires_separation_of_duties": True,
        },
    },
}
DEFAULT_BUNDLE = {**_DEFAULT_BODY, "bundle_sha256": _digest(_DEFAULT_BODY)}


def _validate_bundle(bundle: dict[str, Any]) -> None:
    body = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    if set(body) != REQUIRED_BUNDLE_KEYS:
        raise PolicyBundleError("policy bundle schema keys are invalid")
    if body["policy_id"] != POLICY_ID:
        raise PolicyBundleError("policy id is not the supported release line")
    if not isinstance(body["release"], str) or not body["release"]:
        raise PolicyBundleError("policy release is invalid")
    if body["default_effect"] != "DENY":
        raise PolicyBundleError("policy must fail closed by default")
    if body["allowed_mode"] != "FIXTURE":
        raise PolicyBundleError("policy allowed mode is invalid")
    if set(body["operations"]) != REQUIRED_OPERATIONS:
        raise PolicyBundleError("policy operations are invalid")
    for operation, rule in body["operations"].items():
        if set(rule) != REQUIRED_RULE_KEYS:
            raise PolicyBundleError(f"policy rule schema is invalid for {operation}")
        if not isinstance(rule["required_role"], str) or not isinstance(rule["required_state"], str):
            raise PolicyBundleError(f"policy rule values are invalid for {operation}")
        if not isinstance(rule["requires_evidence"], bool) or not isinstance(rule["requires_separation_of_duties"], bool):
            raise PolicyBundleError(f"policy rule flags are invalid for {operation}")


def load_policy_bundle(path: Path, *, expected_sha256: str | None) -> dict[str, Any]:
    raw = path.read_bytes()
    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise PolicyBundleError("policy bundle hash does not match pinned release")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PolicyBundleError("policy bundle JSON is invalid") from exc
    if not isinstance(body, dict):
        raise PolicyBundleError("policy bundle must be an object")
    bundle = {**body, "bundle_sha256": actual_sha256}
    _validate_bundle(bundle)
    return bundle


def verify_policy_decision(
    decision: dict[str, Any],
    *,
    operation: str,
    principal_id: str,
    session_id: str,
    tenant_id: str,
    resource: dict[str, Any],
    bundle: dict[str, Any] | None = None,
) -> bool:
    active_bundle = bundle or DEFAULT_BUNDLE
    try:
        _validate_bundle(active_bundle)
    except PolicyBundleError:
        return False
    bundle_body = {key: value for key, value in active_bundle.items() if key != "bundle_sha256"}
    if _digest(bundle_body) != active_bundle.get("bundle_sha256"):
        return False
    body = {key: value for key, value in decision.items() if key != "receipt_id"}
    expected_receipt = f"policy-{_digest(body)[:12]}"
    return bool(
        decision.get("policy_id") == active_bundle["policy_id"]
        and decision.get("policy_release") == active_bundle["release"]
        and decision.get("policy_bundle_sha256") == active_bundle["bundle_sha256"]
        and decision.get("effect") == "ALLOW"
        and decision.get("reasons") == []
        and decision.get("operation") == operation
        and decision.get("principal_id") == principal_id
        and decision.get("session_id") == session_id
        and decision.get("tenant_id") == tenant_id
        and decision.get("resource_digest") == _digest(resource)
        and decision.get("receipt_id") == expected_receipt
    )


def evaluate_policy(
    *,
    operation: str,
    principal: dict[str, Any],
    resource: dict[str, Any],
    expected_action_id: str,
    bundle: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_bundle = bundle or DEFAULT_BUNDLE
    _validate_bundle(active_bundle)
    reasons: list[str] = []
    rule = active_bundle["operations"].get(operation)
    if rule is None:
        reasons.append("unsupported_operation")

    if rule is not None:
        if principal.get("tenant_id") != resource.get("tenant_id"):
            reasons.append("tenant_mismatch")
        if rule["required_role"] not in principal.get("roles", []):
            reasons.append("missing_required_role")
        if resource.get("action_id") != expected_action_id:
            reasons.append("resource_mismatch")
        if resource.get("status") != rule["required_state"]:
            reasons.append("invalid_resource_state")
        if rule["requires_evidence"] and not resource.get("evidence_ids"):
            reasons.append("missing_evidence")
        if resource.get("mode") != active_bundle["allowed_mode"]:
            reasons.append("live_execution_not_authorized")
        if rule["requires_separation_of_duties"] and principal.get("id") == resource.get("requester_id"):
            reasons.append("separation_of_duties_violation")

    decision = {
        "policy_id": active_bundle["policy_id"],
        "policy_release": active_bundle["release"],
        "policy_bundle_sha256": active_bundle["bundle_sha256"],
        "effect": "DENY" if reasons else "ALLOW",
        "operation": operation,
        "principal_id": principal.get("id"),
        "session_id": principal.get("session_id"),
        "tenant_id": principal.get("tenant_id"),
        "resource_id": resource.get("action_id"),
        "resource_digest": _digest(resource),
        "reasons": reasons,
    }
    decision["receipt_id"] = f"policy-{_digest(decision)[:12]}"
    return decision
