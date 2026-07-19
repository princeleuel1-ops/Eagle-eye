from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _env() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(ROOT / "src")}


def test_w_transfer_baseline_is_nonvacuous_and_fully_replayable(tmp_path):
    out = tmp_path / "baseline"
    built = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "run_w_transfer_baseline.py"),
            "--out",
            str(out),
        ],
        cwd=ROOT,
        env=_env(),
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    assert "W_TRANSFER_BASELINE_FIXTURE=true" in built.stdout

    replayed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "replay_sealed_evolution.py"),
            str(out / "REPLAY_BUNDLE.json"),
        ],
        cwd=ROOT,
        env=_env(),
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert replayed.returncode == 0, replayed.stdout + replayed.stderr
    assert "REPLAY_RESULT=PASS_FULL_DECISION" in replayed.stdout
    match = re.search(r"DECISIONS_RECOMPUTED=(\d+) MISMATCHED=(\d+)", replayed.stdout)
    assert match is not None
    assert int(match.group(1)) > 0
    assert int(match.group(2)) == 0
