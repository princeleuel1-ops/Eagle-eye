"""V8 complete canonical gate (all inherited mechanisms + W-transfer), fail-closed.

Runs every required gate as a subprocess, records ``{command, exit_code,
elapsed}`` per gate into ``V8_GATE_RESULTS.json``, and prints
``EAGLE_EYE_ZENITH_CHECK_PASS`` only if every required gate is present and
exited zero. A skipped headline mechanism can never produce PASS: the
``REQUIRED_GATES`` list is the guard, and any missing or failed entry fails the
whole check.

Usage: ``PYTHONPATH=src python scripts/run_all_gates.py [results.json]``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

REQUIRED_GATES = [
    # V5 gate 0: setup-portability preflight (loud diagnostic; --strict here so
    # launcher contamination that would corrupt the gate fails fast).
    ("preflight", [PY, "scripts/preflight.py", "--strict"]),
    # inherited headline mechanisms — every one must run and pass; none skipped
    ("dependency-lock", [PY, "-c",
     "import sys; sys.path.insert(0,'src'); from pathlib import Path; "
     "from eagle_eye.provenance import verify_dependency_lock; "
     "r = verify_dependency_lock(Path('.')); "
     "print(r['lock_sha256']); sys.exit(0 if r['all_match'] else 1)"]),
    ("pip-check", [PY, "-m", "pip", "check"]),
    ("tests", [PY, "-m", "pytest", "-q"]),
    ("prediction-court", [PY, "scripts/run_prediction_court.py"]),
    ("fixture", [PY, "scripts/run_fixture.py"]),
    ("verify-python", [PY, "scripts/verify_evidence_room.py",
     "artifacts/runs/latest/evidence-room.zip", "artifacts/runs/latest/trust-registry.json", "tenant-demo"]),
    ("verify-node", ["node", "verifier/verify.mjs", "artifacts/runs/latest/evidence-room.zip",
     "--trust-registry", "artifacts/runs/latest/trust-registry.json", "--expected-tenant", "tenant-demo"]),
    ("governance", [PY, "scripts/run_governance_fixture.py"]),
    ("benchmark-court", [PY, "scripts/run_benchmark_court.py"]),
    ("sealed-evolution", [PY, "scripts/run_sealed_evolution.py", "550"]),
    ("full-decision-replay", [PY, "scripts/replay_sealed_evolution.py",
     "artifacts/evolution/latest/REPLAY_BUNDLE.json"]),
    # Deterministic, explicitly test-fixture baseline for the V8 mechanism
    # court.  This stays separate from the inherited CSPRNG benchmark above:
    # reproducible/non-vacuous mechanism input is not independent evidence.
    ("w-transfer-baseline", [PY, "scripts/run_w_transfer_baseline.py"]),
    # V8: independently replayable W-transfer court. PASS requires both the
    # court execution and its full replay to exit zero; it never requires
    # positive alien-transfer evidence.
    ("w-transfer", [PY, "scripts/run_w_transfer.py",
     "--champion-bundle", "artifacts/transfer/baseline/REPLAY_BUNDLE.json"]),
    ("w-transfer-replay", [PY, "scripts/replay_w_transfer.py",
     "artifacts/transfer/latest/W_TRANSFER_BUNDLE.json",
     "artifacts/transfer/latest/W_TRANSFER_RECEIPT.json"]),
    # V7: recursive self-verifying evolution — every round independently
    # replayed before its evidence may enter the anytime-valid e-process
    # ledger; PASS never requires a crossing (honest outcome preserved).
    ("recursive-evolution", [PY, "scripts/run_recursive_evolution.py", "--rounds", "3"]),
    # V9: the stranger's verifier — a standalone stdlib-only verifier, run in
    # a repo-isolated child interpreter (python3 -I), must ACCEPT every real
    # artifact produced by the gates above (evolution bundle, transfer bundle
    # + receipt, recursive receipt) and REFUSE a doctored battery (forged
    # signatures, splices, reorders, truncation, full re-sign attack,
    # tampered reveal, inflated wealth, flipped claim, tampered heads log).
    # Placed AFTER recursive-evolution so all fifteen court cases always run.
    ("strangers-verifier", [PY, "scripts/run_strangers_court.py"]),
    # V10: live-shadow spine dress rehearsal — full live-tenant path on a
    # test-fixture authority; READY while LIVE is unreachable without a signed
    # production data-authority config, dual-approved and pinned out-of-band.
    ("live-shadow-rehearsal", [PY, "scripts/run_live_shadow_rehearsal.py"]),
    # V11: custody & identity — state ladder, remote round-trip protocol,
    # production signing interlock; production VERIFIED unreachable without
    # the operator ceremony (CUSTODY_ACTIVATION_RUNBOOK).
    ("custody-rehearsal", [PY, "scripts/run_custody_rehearsal.py"]),
    # V12: licensed execution — unarmed by default, dual-control arming with
    # the V11 custody interlock, single-use action licenses, proof-chain
    # receipts, reversal. Production execution unreachable in-repo.
    ("execution-rehearsal", [PY, "scripts/run_execution_rehearsal.py"]),
    # non-vacuous battery fixture: precommitted secret fx2 provably spends a look
    ("battery-fixture", [PY, "-c",
     "import sys; sys.path.insert(0,'src'); "
     "import importlib.util; from pathlib import Path; "
     "spec = importlib.util.spec_from_file_location('rse','scripts/run_sealed_evolution.py'); "
     "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); "
     "sys.exit(m.main(live_seed=550, evaluator_secret='fx2', "
     "out_dir=Path('artifacts/evolution/battery-fixture'), suite_scale=1))"]),
    ("mutation-battery", [PY, "scripts/replay_mutation_battery.py",
     "artifacts/evolution/battery-fixture/REPLAY_BUNDLE.json",
     "artifacts/evolution/battery-fixture/MUTATION_BATTERY_RESULTS.json"]),
    ("power-analysis", [PY, "scripts/power_analysis.py"]),
    ("parameter-shift", [PY, "scripts/run_parameter_shift_eval.py"]),
    ("independent-generator", [PY, "scripts/run_independent_generator_eval.py"]),
    ("semantic-check", [PY, "scripts/semantic_check.py"]),
    ("dom-contract", ["node", "verifier/dom_contract_test.mjs"]),
    ("browser", [PY, "scripts/browser_verification.py"]),
    # V6 PILOT FORGE gates — the operational spine. Each runs REAL processes
    # (separate evaluator + cockpit) and fails the whole check if degraded.
    # (Pilot unit + evaluator-process tests already run inside the `tests`
    # gate above; these gates exercise the live end-to-end system.)
    ("pilot-smoke", [PY, "scripts/pilot_smoke.py"]),
    ("failure-court", [PY, "scripts/failure_court.py"]),
    ("pilot-browser", [PY, "scripts/pilot_browser_verification.py"]),
    ("pilot-performance", [PY, "scripts/pilot_performance.py"]),
    # package-verify LAST: it hashes the final tree, so all generated
    # artifacts above must already exist.
    ("package-verify", [PY, "scripts/verify_package.py", "--tree"]),
]


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "artifacts" / "check" / "V8_GATE_RESULTS.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # V5 portability: scrub any inherited PYTHONHOME and set PYTHONPATH to
    # EXACTLY the project src (overriding any launcher-injected value), so no
    # gate subprocess can resolve foreign packages.
    env = {k: v for k, v in os.environ.items() if k != "PYTHONHOME"}
    env["PYTHONPATH"] = str(ROOT / "src")
    rows = []
    overall_start = time.time()
    for name, command in REQUIRED_GATES:
        print(f"=== GATE {name} ===", flush=True)
        start = time.time()
        result = subprocess.run(command, cwd=ROOT, env=env,
                                capture_output=True, text=True)
        elapsed = round(time.time() - start, 1)
        tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-4:])
        print(tail)
        print(f"--- {name}: exit={result.returncode} ({elapsed}s)", flush=True)
        rows.append({"gate": name, "command": " ".join(command[:6]) + (" ..." if len(command) > 6 else ""),
                     "exit_code": result.returncode, "elapsed_s": elapsed,
                     "tail": tail})
        if result.returncode != 0:
            # fail-closed: later gates may depend on earlier artifacts
            break
    ran = {r["gate"] for r in rows}
    required = {name for name, _ in REQUIRED_GATES}
    missing = sorted(required - ran)
    all_zero = all(r["exit_code"] == 0 for r in rows)
    complete = not missing
    ok = all_zero and complete
    receipt = {
        "spec": "v8-canonical-gate/8.0",
        "gates_required": sorted(required),
        "gates_ran": sorted(ran),
        "gates_missing": missing,
        "rows": rows,
        "all_exit_codes_zero": all_zero,
        "completeness_guard": "PASS requires every required gate present with exit 0; skipped mechanisms can never PASS",
        "elapsed_s": round(time.time() - overall_start, 1),
        "pass": ok,
    }
    out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True))
    if ok:
        print("EAGLE_EYE_ZENITH_CHECK_PASS")
    else:
        failed = [r["gate"] for r in rows if r["exit_code"] != 0]
        print(f"EAGLE_EYE_ZENITH_CHECK_FAIL failed={failed} missing={missing}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
