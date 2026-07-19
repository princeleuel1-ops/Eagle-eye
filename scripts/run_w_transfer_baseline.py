"""Build the deterministic, non-vacuous V7 baseline admitted by V8 W-transfer.

This is an explicitly labeled SYNTHETIC TEST FIXTURE.  Its public evaluator
secret exists to make the V8 mechanism court reproducible and non-vacuous; it
must not be cited as independent holdout or external evidence.
"""

from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "transfer" / "baseline"
FIXTURE_SECRET = "w-transfer-v8-fixed-court"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location(
        "sealed_evolution_for_w_transfer",
        ROOT / "scripts" / "run_sealed_evolution.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("sealed-evolution loader unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    code = module.main(
        live_seed=550,
        evaluator_secret=FIXTURE_SECRET,
        out_dir=args.out,
        suite_scale=3,
    )
    if code == 0:
        print("W_TRANSFER_BASELINE_FIXTURE=true")
        print(f"W_TRANSFER_BASELINE_BUNDLE={args.out / 'REPLAY_BUNDLE.json'}")
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
