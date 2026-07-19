"""V12 licensed-execution DRESS REHEARSAL — the first-action machinery proven
on a test-fixture arming and a local outbox; production execution unreachable.

Writes artifacts/execution/EXECUTION_REHEARSAL_RECEIPT.json.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eagle_eye.licensed_execution import (  # noqa: E402
    ARMED_TEST_FIXTURE, UNARMED, ExecutionRefused, LicensedExecutor,
    LocalOutboxAdapter, issue_action_token, sign_arming_config, verify_arming,
)
from eagle_eye.pilot.kms import EphemeralKeyProvider  # noqa: E402
from eagle_eye.prior_registry import canonical_bytes, sha256_hex  # noqa: E402
from eagle_eye.signing import generate_demo_keypair, key_id  # noqa: E402

OUT = ROOT / "artifacts" / "execution"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    stages = []

    def rec(name, ok, detail=""):
        stages.append({"stage": name, "ok": bool(ok), "detail": detail})
        print(f"{'OK  ' if ok else 'FAIL'} {name}{': ' + detail if detail and not ok else ''}")

    priv, pub = generate_demo_keypair()
    pinned = {key_id(pub): pub}

    # 1. unarmed by default
    v0 = verify_arming(None, trusted_authority_keys=pinned)
    rec("unarmed_by_default", v0["arm_state"] == UNARMED)

    # 2. production arming refused without verified production custody
    prod = sign_arming_config({"spec": "eagle-eye-execution-arming/1.0",
                               "arming_class": "production", "tenant_id": "tenant-real",
                               "action_classes": ["notify_webhook"], "max_actions": 1,
                               "authorized_by": [{"sub": "ciso"}, {"sub": "coo"}],
                               "valid_from_epoch": time.time() - 60,
                               "valid_until_epoch": time.time() + 3600}, priv, pub)
    vp = verify_arming(prod, trusted_authority_keys=pinned, custody_descriptor=None)
    rec("production_arming_needs_verified_custody",
        vp["arm_state"] == UNARMED and any("custody" in r for r in vp["reasons"]))

    # 3. single-approver refused
    single = sign_arming_config({**{k: prod[k] for k in
                                    ("spec", "arming_class", "tenant_id", "action_classes",
                                     "max_actions", "valid_from_epoch", "valid_until_epoch")},
                                 "arming_class": "test_fixture",
                                 "authorized_by": [{"sub": "solo"}]}, priv, pub)
    rec("single_approver_unarmed",
        verify_arming(single, trusted_authority_keys=pinned)["arm_state"] == UNARMED)

    # 4. test-fixture arming works
    fix = sign_arming_config({"spec": "eagle-eye-execution-arming/1.0",
                              "arming_class": "test_fixture", "tenant_id": "tenant-fixture-x",
                              "action_classes": ["notify_webhook"], "max_actions": 2,
                              "authorized_by": [{"sub": "op-a"}, {"sub": "op-b"}],
                              "valid_from_epoch": time.time() - 60,
                              "valid_until_epoch": time.time() + 3600}, priv, pub)
    v = verify_arming(fix, trusted_authority_keys=pinned)
    rec("fixture_arming_armed", v["arm_state"] == ARMED_TEST_FIXTURE)

    adapter = LocalOutboxAdapter(OUT / "outbox.jsonl")
    executor = LicensedExecutor(verification=v, adapter=adapter,
                                trusted_authority_keys=pinned,
                                signer=EphemeralKeyProvider())
    evidence = sha256_hex(canonical_bytes({"case": "fixture-evidence"}))
    tok_body = {"spec": "eagle-eye-licensed-execution/1.0", "action_id": "act-001",
                "action_class": "notify_webhook", "evidence_digest": evidence,
                "approval_receipt_id": "approval-fixture-001",
                "arming_config_sha256": v["config_sha256"],
                "issued_at_epoch": time.time()}
    token = issue_action_token(tok_body, priv, pub)

    # 5. THE FIRST ACTION — full proof chain, local outbox, reversible
    receipt = executor.execute(action_id="act-001", action_class="notify_webhook",
                               payload={"message": "fixture hello"},
                               principal={"sub": "op-a", "roles": ["requester"]},
                               evidence_digest=evidence,
                               approval_receipt_id="approval-fixture-001", token=token)
    chain_ok = all(receipt.get(k) for k in
                   ("principal", "evidence_digest", "approval_receipt_id",
                    "arming_config_sha256", "token_sha256", "adapter", "outcome",
                    "receipt_sha256", "receipt_signature_b64"))
    rec("first_action_executes_with_full_proof_chain",
        chain_ok and receipt["outcome"]["delivered"] is True)

    # 6. replayed license refused (single-use)
    try:
        executor.execute(action_id="act-001", action_class="notify_webhook",
                         payload={"message": "again"}, principal={"sub": "op-a"},
                         evidence_digest=evidence,
                         approval_receipt_id="approval-fixture-001", token=token)
        rec("license_single_use", False)
    except ExecutionRefused:
        rec("license_single_use", True)

    # 7. tampered license refused
    forged = dict(token); forged["action_id"] = "act-002"
    try:
        executor.execute(action_id="act-002", action_class="notify_webhook",
                         payload={}, principal={"sub": "op-a"},
                         evidence_digest=evidence,
                         approval_receipt_id="approval-fixture-001", token=forged)
        rec("tampered_license_refused", False)
    except ExecutionRefused:
        rec("tampered_license_refused", True)

    # 8. non-allowlisted action class refused
    tok2 = issue_action_token({**tok_body, "action_id": "act-003",
                               "action_class": "delete_everything"}, priv, pub)
    try:
        executor.execute(action_id="act-003", action_class="delete_everything",
                         payload={}, principal={"sub": "op-a"},
                         evidence_digest=evidence,
                         approval_receipt_id="approval-fixture-001", token=tok2)
        rec("non_allowlisted_class_refused", False)
    except ExecutionRefused:
        rec("non_allowlisted_class_refused", True)

    # 9. reversal binds the original receipt
    reversal = executor.reverse(receipt)
    rec("reversal_binds_original",
        reversal["reverses_receipt_sha256"] == receipt["receipt_sha256"])

    # 10. unarmed executor refuses everything
    try:
        LicensedExecutor(verification=v0, adapter=adapter,
                         trusted_authority_keys=pinned, signer=EphemeralKeyProvider())
        rec("unarmed_probe", True)  # construction allowed; execute must refuse
        ex0 = LicensedExecutor(verification=v0, adapter=adapter,
                               trusted_authority_keys=pinned, signer=EphemeralKeyProvider())
        try:
            ex0.execute(action_id="x", action_class="notify_webhook", payload={},
                        principal={}, evidence_digest=evidence,
                        approval_receipt_id="a", token=token)
            rec("unarmed_execution_refused", False)
        except ExecutionRefused:
            rec("unarmed_execution_refused", True)
    except Exception as exc:  # noqa: BLE001
        rec("unarmed_probe", False, str(exc))

    all_ok = all(x["ok"] for x in stages)
    receipt_doc = {"spec": "eagle-eye-execution-rehearsal/1.0", "stages": stages,
                   "passed": sum(1 for x in stages if x["ok"]), "total": len(stages),
                   "production_execution_reachable_in_this_run": False,
                   "network_used": False, "external_action": False,
                   "elapsed_s": round(time.time() - started, 2)}
    receipt_doc["receipt_id"] = "exec-" + sha256_hex(canonical_bytes(receipt_doc))[:12]
    (OUT / "EXECUTION_REHEARSAL_RECEIPT.json").write_text(
        json.dumps(receipt_doc, indent=2, sort_keys=True))
    print(f"REHEARSAL_STAGES={receipt_doc['passed']}/{receipt_doc['total']}")
    print("PRODUCTION_EXECUTION_REACHABLE=false")
    print(f"RECEIPT_ID={receipt_doc['receipt_id']}")
    print(f"EXECUTION_REHEARSAL_PASS={'true' if all_ok else 'false'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
