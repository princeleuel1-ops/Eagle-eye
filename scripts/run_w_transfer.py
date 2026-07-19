from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from eagle_eye.prior_registry import canonical_bytes, sha256_hex
from eagle_eye.transfer import (
    ALIEN_TRANSFER_EVIDENCE_EARNED,
    NO_ALIEN_TRANSFER_EVIDENCE_EARNED,
    WTransferCourt,
    build_bundle,
    build_preregistered_protocol,
    build_receipt,
    evaluate_family_seed,
    family_panel,
)

ROOT = Path(__file__).resolve().parents[1]


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--champion-bundle", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "transfer" / "latest")
    args = parser.parse_args()

    champion_bundle_path = args.champion_bundle.resolve()
    if not champion_bundle_path.exists():
        print(f"W_TRANSFER_FAIL=missing champion bundle at {champion_bundle_path}")
        return 1
    out_dir = args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    champion_bundle_sha256 = sha256_file(champion_bundle_path)
    champion_bundle = json.loads(champion_bundle_path.read_text())
    champion_config = champion_bundle["final_champion_config"]
    champion_config_hash = sha256_hex(canonical_bytes(champion_config))
    protocol = build_preregistered_protocol(
        champion_config_hash=champion_config_hash,
        family_manifests=family_panel(),
    )
    replay_status = replay_champion_bundle(champion_bundle_path)
    if not replay_status["passed"]:
        print("W_TRANSFER_FAIL=champion bundle did not pass full-decision replay")
        return 1

    court = WTransferCourt(protocol, champion_bundle_sha256=champion_bundle_sha256)
    evaluations = []
    for family_manifest in protocol["family_manifests"]:
        for seed in protocol["seeds"]:
            evaluation = evaluate_family_seed(
                family_manifest=family_manifest,
                world_seed=seed,
                champion_config=champion_config,
                target_plan=protocol["target_plan"],
            )
            court.admit_seed_evidence(
                family_manifest=family_manifest,
                world_seed=seed,
                registry_release=evaluation["registry_release"],
                case_rows=evaluation["case_rows"],
            )
            evaluations.append(evaluation)

    receipt = build_receipt(
        protocol=protocol,
        champion_bundle_sha256=champion_bundle_sha256,
        champion_config_hash=champion_config_hash,
        evaluations=evaluations,
        court=court,
        replay_status=replay_status,
    )
    bundle = build_bundle(
        champion_bundle_path=champion_bundle_path,
        champion_bundle_sha256=champion_bundle_sha256,
        champion_config=champion_config,
        protocol=protocol,
        evaluations=evaluations,
        court=court,
        replay_status=replay_status,
        receipt=receipt,
    )
    (out_dir / "W_TRANSFER_BUNDLE.json").write_text(json.dumps(bundle, indent=2, sort_keys=True))
    (out_dir / "W_TRANSFER_RECEIPT.json").write_text(json.dumps(receipt, indent=2, sort_keys=True))

    ok = all(receipt["mechanism_checks"].values())
    print(f"UNITS_EVALUATED={len(evaluations)}")
    print(f"STREAMS={protocol['stream_count']}")
    print(f"HISTORY_ROWS={receipt['history_row_count']}")
    print(receipt["headline_claim_status"])
    print(f"W_TRANSFER_PASS={'true' if ok else 'false'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
