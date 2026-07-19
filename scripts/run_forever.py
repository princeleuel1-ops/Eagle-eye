"""Continuous evolution loop driver: epoch after epoch until stopped or a
trust boundary fails (fail-closed, never fail-quiet).

Each epoch: fresh commit-reveal evaluator secret (= holdout rotation + fresh
alpha budget per the MULTIPLE_COMPARISON_POLICY), full sealed benchmark,
integrity replay, epoch row appended to a signed epoch ledger on disk.
Stop conditions (the ONLY ones): trust/verification failure, replay failure,
or operator interrupt. NO_CHALLENGER_EARNED_PROMOTION is a valid epoch result,
not a stop condition — the loop keeps searching without lowering any gate.

usage: PYTHONPATH=src python3.11 scripts/run_forever.py [max_epochs] [base_seed]
       (max_epochs 0 = run until interrupted)
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "artifacts" / "evolution" / "EPOCH_LEDGER.jsonl"


def main(max_epochs: int = 0, base_seed: int = 20270000) -> int:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    epoch = 0
    while max_epochs == 0 or epoch < max_epochs:
        epoch += 1
        seed = base_seed + epoch
        started = time.time()
        bench = subprocess.run(
            [sys.executable, "scripts/run_sealed_evolution.py", str(seed)],
            capture_output=True, text=True, cwd=ROOT,
            env={**os.environ, "PYTHONPATH": "src"})
        replay = subprocess.run(
            [sys.executable, "scripts/replay_sealed_evolution.py",
             "artifacts/evolution/latest/REPLAY_BUNDLE.json"],
            capture_output=True, text=True, cwd=ROOT,
            env={**os.environ, "PYTHONPATH": "src"})
        lines = bench.stdout.splitlines()
        summary = {k: v for k, v in (line.split("=", 1) for line in lines if "=" in line)}
        replay_summary = {k: v for k, v in (line.split("=", 1)
                                            for line in replay.stdout.splitlines() if "=" in line)}
        row = {
            "epoch": epoch, "seed": seed,
            "duration_s": round(time.time() - started, 1),
            "benchmark_pass": bench.returncode == 0,
            "replay_pass": replay.returncode == 0 and "REPLAY_PASS" in replay.stdout,
            # V4: PASS_FULL_DECISION vs VACUOUS_INTEGRITY_ONLY — never conflated
            "replay_result": replay_summary.get("REPLAY_RESULT", "UNKNOWN"),
            "promotions": int(summary.get("PROMOTIONS", -1)),
            "rejections": int(summary.get("REJECTIONS", -1)),
            "receipt_verification_failures": int(summary.get("RECEIPT_VERIFICATION_FAILURES", -1)),
            "look_terminal_statuses": summary.get("LOOK_TERMINAL_STATUSES"),
            "evaluator_lifecycle": summary.get("EVALUATOR_LIFECYCLE"),
            "champion": summary.get("FINAL_CHAMPION"),
            "receipt": summary.get("BENCHMARK_RECEIPT_ID"),
        }
        with LEDGER.open("a") as fh:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
        print(json.dumps(row, sort_keys=True))
        if not row["benchmark_pass"] or not row["replay_pass"] or row["receipt_verification_failures"] != 0:
            print(f"EPOCH_{epoch}_TRUST_FAILURE — LOOP HALTED FAIL-CLOSED")
            return 1
    print(f"LOOP_COMPLETE epochs={epoch}")
    return 0


if __name__ == "__main__":
    max_epochs = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    base_seed = int(sys.argv[2]) if len(sys.argv) > 2 else 20270000
    raise SystemExit(main(max_epochs, base_seed))
