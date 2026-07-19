import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
run = json.loads((root / "artifacts/runs/latest/run.json").read_text())
identity = run["identity_harness"]
governance = run["governance_harness"]
audit = run["audit_ledger"]
policy_bundle = run["policy_bundle"]
request = governance["request"]
receipt = governance["approval"]

if identity["principals_verified"] != 2 or not all(item["verified"] for item in identity["receipts"]):
    raise SystemExit("identity harness is not verified")
if receipt["tenant_id"] != audit["commitment"]["tenant_id"]:
    raise SystemExit("governance tenant does not match audit commitment")
if receipt["receipt_id"] != audit["events"][-1]["payload"]["receipt_id"]:
    raise SystemExit("approval receipt is not bound to audit head")
if audit["events"][0]["payload"]["session_id"] != identity["receipts"][0]["session_id"]:
    raise SystemExit("requester session is not bound to audit event")
if audit["events"][1]["payload"]["session_id"] != identity["receipts"][1]["session_id"]:
    raise SystemExit("approver session is not bound to audit event")
if audit["events"][0]["payload"].get("policy_receipt_id") != request["policy_decision"]["receipt_id"]:
    raise SystemExit("request policy receipt is not bound to audit event")
if audit["events"][1]["payload"].get("policy_receipt_id") != receipt["policy_decision"]["receipt_id"]:
    raise SystemExit("approval policy receipt is not bound to audit event")
for decision in (request["policy_decision"], receipt["policy_decision"]):
    if decision.get("policy_release") != policy_bundle["release"]:
        raise SystemExit("policy decision release does not match active bundle")
    if decision.get("policy_bundle_sha256") != policy_bundle["bundle_sha256"]:
        raise SystemExit("policy decision hash does not match active bundle")

output = root / "artifacts/governance/latest"
output.mkdir(parents=True, exist_ok=True)
(output / "request.json").write_text(json.dumps(request, indent=2, sort_keys=True))
(output / "approval-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True))
print(f"GOVERNANCE_ACTION={receipt['action_id']}")
print(f"IDENTITY_PRINCIPALS_VERIFIED={identity['principals_verified']}")
print(f"REQUEST_POLICY_RECEIPT={request['policy_decision']['receipt_id']}")
print(f"APPROVAL_POLICY_RECEIPT={receipt['policy_decision']['receipt_id']}")
print(f"POLICY_DECISIONS_VERIFIED=2")
print(f"POLICY_RELEASE={policy_bundle['release']}")
print(f"POLICY_BUNDLE_SHA256={policy_bundle['bundle_sha256']}")
print(f"DUAL_CONTROL_VERIFIED={str(receipt['dual_control_verified']).lower()}")
print(f"GOVERNANCE_TENANT_VERIFIED={str(receipt['tenant_verified']).lower()}")
print(f"SHADOW_ONLY={str(not receipt['external_execution']).lower()}")
print(f"ACTION_STATUS={receipt['action_status']}")
print(f"APPROVAL_RECEIPT_ID={receipt['receipt_id']}")
print(f"GOVERNANCE_AUDIT_HEAD={audit['commitment']['head']}")
