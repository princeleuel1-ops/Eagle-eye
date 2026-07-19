"""V4 blocker 3: mandatory replay mutation battery.

Loads a REAL replay bundle, applies one binding-field mutation at a time, and
requires the full-decision replay CLI to exit NONZERO for every mutant (and
ZERO for the unmutated baseline). Covers every field class the audit listed:

  final_registry_manifest_sha256, controller_run_seed, cycle_cutoffs,
  live_world, policy_registry, resolutions, candidate ID, snapshot ID,
  registry binding, alpha fields, aggregate metrics, final-audit values,
  lineage state and reasons — plus evaluator secret, suite scale,
  genesis config, and committed prediction blocks.

Mutations inside signed chain rows are expected to be caught by signature
verification FIRST (that is the designed defense-in-depth); the battery
records which check caught each mutant.

usage: PYTHONPATH=src python scripts/replay_mutation_battery.py [bundle.json] [out.json]
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUNDLE = ROOT / "artifacts" / "evolution" / "latest" / "REPLAY_BUNDLE.json"


def first_succeeded_result_index(bundle) -> int:
    for i, row in enumerate(bundle["chains"]["evaluator"]["rows"]):
        if (row["body"]["kind"] == "promotion_look_result"
                and row["body"]["terminal_status"] == "SUCCEEDED"):
            return i
    return -1


def first_look_lineage_index(bundle) -> int:
    for i, row in enumerate(bundle["chains"]["lineage"]["rows"]):
        if row["body"].get("evaluator_response_hash"):
            return i
    return -1


def final_audit_result_index(bundle) -> int:
    for i, row in enumerate(bundle["chains"]["evaluator"]["rows"]):
        if row["body"]["kind"] == "final_audit_result":
            return i
    return -1


def build_mutations(bundle) -> list[tuple[str, str]]:
    """Returns (name, python-lambda-source) pairs; each lambda mutates a deep
    copy of the bundle in place. Indices are resolved against THIS bundle."""
    ev_idx = first_succeeded_result_index(bundle)
    ln_idx = first_look_lineage_index(bundle)
    fa_idx = final_audit_result_index(bundle)
    policy_key = next(iter(bundle["policy_registry"]))
    pred_key = next(iter(bundle["predictions"]))
    muts: list[tuple[str, callable]] = [
        ("final_registry_manifest_sha256",
         lambda b: b.update(final_registry_manifest_sha256="0" * 64)),
        ("controller_run_seed",
         lambda b: b.update(controller_run_seed=b["controller_run_seed"] + 1)),
        ("cycle_cutoffs",
         lambda b: b["cycle_cutoffs"].__setitem__(0, "2025-05-02")),
        ("live_world_seed",
         lambda b: b["live_world"].update(world_seed=b["live_world"]["world_seed"] + 1)),
        ("policy_registry_follow_prob",
         lambda b: b["policy_registry"][policy_key].update(follow_prob=0.9)),
        ("resolutions_outcome_value",
         lambda b: b["resolutions"][0].update(
             outcome_value_micro=b["resolutions"][0]["outcome_value_micro"] + 1)),
        ("alpha_total",
         lambda b: b["evaluator_config"].update(alpha_total=0.10)),
        ("evaluator_secret",
         lambda b: b["evaluator_reveal"].update(evaluator_secret="forged-secret")),
        ("suite_scale",
         lambda b: b["evaluator_config"].update(suite_scale=b["evaluator_config"]["suite_scale"] + 1)),
        ("genesis_config",
         lambda b: b["genesis_config"].update(**{"selector.k_max": 12})),
        ("committed_prediction_block",
         lambda b: b["predictions"][pred_key].update(K=999)),
        ("grown_task_content",
         lambda b: (b["grown_tasks"][0]["task"].update(as_of_end="2031-01-01")
                    if b["grown_tasks"] else b.update(grown_tasks=[{"forged": True}]))),
        ("base_registry_manifest",
         lambda b: b.update(base_registry_manifest_sha256="f" * 64)),
    ]
    if ln_idx >= 0:
        muts += [
            ("lineage_candidate_id",
             lambda b: b["chains"]["lineage"]["rows"][ln_idx]["body"]["candidate"].update(
                 candidate_id="cand-forged00000")),
            ("lineage_snapshot_id",
             lambda b: b["chains"]["lineage"]["rows"][ln_idx]["body"].update(
                 dataset_snapshot_id="snap-forged")),
            ("lineage_registry_binding",
             lambda b: b["chains"]["lineage"]["rows"][ln_idx]["body"].update(
                 registry_manifest_sha256="a" * 64)),
            ("lineage_state_and_reasons",
             lambda b: b["chains"]["lineage"]["rows"][ln_idx]["body"].update(
                 state="PROMOTED", reasons=[])),
        ]
    if ev_idx >= 0:
        muts.append(
            ("aggregate_metrics",
             lambda b: b["chains"]["evaluator"]["rows"][ev_idx]["body"]
             ["challenger_aggregates"]["metrics"].update(
                 nll=b["chains"]["evaluator"]["rows"][ev_idx]["body"]
                 ["challenger_aggregates"]["metrics"]["nll"] - 50000)))
    if fa_idx >= 0:
        muts.append(
            ("final_audit_values",
             lambda b: b["chains"]["evaluator"]["rows"][fa_idx]["body"]
             ["aggregates"]["metrics"].update(
                 nll=b["chains"]["evaluator"]["rows"][fa_idx]["body"]
                 ["aggregates"]["metrics"]["nll"] - 50000)))
    return muts


def run_replay(bundle_path: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "replay_sealed_evolution.py"),
         str(bundle_path), *flags],
        capture_output=True, text=True, cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")})


def main() -> int:
    bundle_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BUNDLE
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else bundle_path.parent / "MUTATION_BATTERY_RESULTS.json"
    bundle = json.loads(bundle_path.read_text())
    looks = sum(1 for r in bundle["chains"]["evaluator"]["rows"]
                if r["body"]["kind"] == "promotion_look_charge")
    rows = []
    started = time.time()
    baseline = run_replay(bundle_path, "--fail-fast")
    baseline_marker = "REPLAY_RESULT=PASS_FULL_DECISION" in baseline.stdout
    vacuous = "VACUOUS" in baseline.stdout
    rows.append({"name": "UNMUTATED_BASELINE", "exit_code": baseline.returncode,
                 "expected": 0, "ok": baseline.returncode == 0,
                 "full_decision": baseline_marker, "vacuous": vacuous})
    print(f"BASELINE exit={baseline.returncode} full_decision={baseline_marker} vacuous={vacuous}")
    with tempfile.TemporaryDirectory() as td:
        for name, mutate in build_mutations(bundle):
            mutant = copy.deepcopy(bundle)
            mutate(mutant)
            mpath = Path(td) / f"mutant-{name}.json"
            mpath.write_text(json.dumps(mutant, sort_keys=True))
            t0 = time.time()
            result = run_replay(mpath, "--fail-fast", "--skip-node")
            caught_by = next((line.split("=")[0] for line in result.stdout.splitlines()
                              if line.endswith("=FAIL") or "=FAIL " in line), "UNKNOWN")
            ok = result.returncode != 0
            rows.append({"name": name, "exit_code": result.returncode, "expected": "nonzero",
                         "ok": ok, "caught_by": caught_by,
                         "elapsed_s": round(time.time() - t0, 1)})
            print(f"MUTANT {name}: exit={result.returncode} caught_by={caught_by} "
                  f"{'OK' if ok else 'NOT DETECTED — FAIL'}")
    all_ok = all(r["ok"] for r in rows) and not vacuous and looks > 0
    receipt = {
        "spec": "replay-mutation-battery/4.0",
        "bundle": str(bundle_path),
        "looks_in_bundle": looks,
        "baseline_full_decision": baseline_marker,
        "mutations_total": len(rows) - 1,
        "mutations_detected": sum(1 for r in rows[1:] if r["ok"]),
        "rows": rows,
        "elapsed_s": round(time.time() - started, 1),
        "pass": all_ok,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True))
    print(f"MUTATIONS_DETECTED={receipt['mutations_detected']}/{receipt['mutations_total']}")
    print(f"MUTATION_BATTERY_{'PASS' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
