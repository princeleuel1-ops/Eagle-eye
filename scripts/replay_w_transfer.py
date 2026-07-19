from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from eagle_eye.prior_registry import canonical_bytes, sha256_hex
from eagle_eye.transfer import (
    W_TRANSFER_BUNDLE_SPEC,
    W_TRANSFER_RECEIPT_SPEC,
    WTransferCourt,
    build_bundle,
    build_preregistered_protocol,
    build_receipt,
    evaluate_family_seed,
    family_panel,
)
from eagle_eye.signed_chain import verify_chain

ROOT = Path(__file__).resolve().parents[1]
FAIL_FAST = "--fail-fast" in sys.argv
_failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> bool:
    print(f"{name}={'PASS' if condition else 'FAIL'}" + (f" ({detail})" if detail and not condition else ""))
    if not condition:
        _failures.append(name)
        if FAIL_FAST:
            print("W_TRANSFER_REPLAY=FAIL_FAST")
            raise SystemExit(1)
    return condition


def sha256_file(path: Path) -> str:
    h = __import__("hashlib").sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def replay_champion_bundle(bundle_path: Path) -> dict[str, object]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "replay_sealed_evolution.py"), str(bundle_path)],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )
    stdout = proc.stdout
    mismatched = None
    for line in stdout.splitlines():
        if line.startswith("DECISIONS_RECOMPUTED="):
            try:
                mismatched = int(line.rsplit("MISMATCHED=", 1)[1])
            except (IndexError, ValueError):
                mismatched = None
    passed = (
        proc.returncode == 0
        and "REPLAY_RESULT=PASS_FULL_DECISION" in stdout
        and mismatched == 0
    )
    return {
        "passed": passed,
        "returncode": proc.returncode,
        "decisions_mismatched": mismatched,
        "stdout_sha256": sha256_hex(stdout.encode()),
        "tail": stdout.strip().splitlines()[-5:] if stdout.strip() else [],
    }


def strip_signature(row: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in row.items() if key not in ("signer_key_id", "signature_b64")}


def strip_anchor(anchor: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in anchor.items() if key not in ("signer_key_id", "anchor_signature_b64")}


def strip_bundle_runtime_fields(bundle: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in bundle.items() if key not in ("chains", "signer_registry")}


def main() -> int:
    bundle_path = Path(sys.argv[1]).resolve()
    receipt_path = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else bundle_path.with_name("W_TRANSFER_RECEIPT.json")
    bundle = json.loads(bundle_path.read_text())
    receipt = json.loads(receipt_path.read_text())

    check("BUNDLE_SPEC", bundle.get("spec") == W_TRANSFER_BUNDLE_SPEC, str(bundle.get("spec")))
    check("RECEIPT_SPEC", receipt.get("spec") == W_TRANSFER_RECEIPT_SPEC, str(receipt.get("spec")))

    champion_bundle_path = Path(bundle["champion_bundle_path"])
    check("CHAMPION_BUNDLE_EXISTS", champion_bundle_path.exists(), str(champion_bundle_path))
    if champion_bundle_path.exists():
        check("CHAMPION_BUNDLE_SHA256", sha256_file(champion_bundle_path) == bundle["champion_bundle_sha256"])
        champion_replay = replay_champion_bundle(champion_bundle_path)
    else:
        champion_replay = {"passed": False, "returncode": None, "decisions_mismatched": None, "stdout_sha256": None, "tail": []}
    check("CHAMPION_REPLAY_PASS", bool(champion_replay["passed"]))

    champion_config_hash = sha256_hex(canonical_bytes(bundle["champion_config"]))
    check("CHAMPION_CONFIG_HASH", champion_config_hash == bundle["champion_config_hash"])

    expected_protocol = build_preregistered_protocol(
        champion_config_hash=champion_config_hash,
        family_manifests=family_panel(),
        baseline_release=bundle["baseline_release"],
    )
    check("PROTOCOL_REGENERATED", canonical_bytes(expected_protocol) == canonical_bytes(bundle["protocol"]))

    expected_units = [
        (manifest["family_id"], seed)
        for manifest in expected_protocol["family_manifests"]
        for seed in expected_protocol["seeds"]
    ]
    actual_units = [(row["family_id"], row["world_seed"]) for row in bundle["evaluations"]]
    check("UNIT_ORDER_COMPLETE", actual_units == expected_units)

    court = WTransferCourt(expected_protocol, champion_bundle_sha256=bundle["champion_bundle_sha256"])
    expected_evaluations = []
    for family_manifest in expected_protocol["family_manifests"]:
        for seed in expected_protocol["seeds"]:
            evaluation = evaluate_family_seed(
                family_manifest=family_manifest,
                world_seed=seed,
                champion_config=bundle["champion_config"],
                target_plan=expected_protocol["target_plan"],
            )
            court.admit_seed_evidence(
                family_manifest=family_manifest,
                world_seed=seed,
                registry_release=evaluation["registry_release"],
                case_rows=evaluation["case_rows"],
            )
            expected_evaluations.append(evaluation)
    check("EVALUATIONS_REGENERATED", canonical_bytes(expected_evaluations) == canonical_bytes(bundle["evaluations"]))

    expected_receipt = build_receipt(
        protocol=expected_protocol,
        champion_bundle_sha256=bundle["champion_bundle_sha256"],
        champion_config_hash=champion_config_hash,
        evaluations=expected_evaluations,
        court=court,
        replay_status=champion_replay,
    )
    expected_bundle = build_bundle(
        champion_bundle_path=champion_bundle_path,
        champion_bundle_sha256=bundle["champion_bundle_sha256"],
        champion_config=bundle["champion_config"],
        protocol=expected_protocol,
        evaluations=expected_evaluations,
        court=court,
        replay_status=champion_replay,
        receipt=expected_receipt,
    )

    actual_chain = bundle["chains"]["transfer"]
    check(
        "CHAIN_TRANSFER_VERIFIED",
        verify_chain(
            actual_chain["rows"],
            actual_chain["anchor"],
            bundle["signer_registry"],
            expected_tenant="tenant-demo",
            expected_chain_id="w-transfer-history",
            expected_run_id=f"run-w-transfer-{bundle['champion_bundle_sha256'][:8]}",
        )["verified"],
    )
    check(
        "CHAIN_TRANSFER_ROWS",
        [strip_signature(row) for row in actual_chain["rows"]] == [strip_signature(row) for row in expected_bundle["chains"]["transfer"]["rows"]],
    )
    check(
        "CHAIN_TRANSFER_ANCHOR",
        strip_anchor(actual_chain["anchor"]) == strip_anchor(expected_bundle["chains"]["transfer"]["anchor"]),
    )
    check(
        "BUNDLE_CORE_REGENERATED",
        canonical_bytes(strip_bundle_runtime_fields(expected_bundle))
        == canonical_bytes(strip_bundle_runtime_fields(bundle)),
    )
    check("RECEIPT_REGENERATED", canonical_bytes(expected_receipt) == canonical_bytes(receipt))
    check("RECEIPT_ID_BOUND", bundle["receipt_id"] == receipt["receipt_id"] == expected_receipt["receipt_id"])

    ok = not _failures and len(expected_evaluations) > 0
    print(f"UNITS_REGENERATED={len(expected_evaluations)}/{len(expected_units)}")
    print(f"STREAMS={expected_protocol['stream_count']}")
    print(f"RECEIPT_ID={expected_receipt['receipt_id']}")
    print(f"W_TRANSFER_REPLAY={'PASS_COMPLETE' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
