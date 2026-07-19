"""V7 recursive loop: one full round through the REAL pipeline — sealed run
with feedback generation, independent replay in a child process, fail-closed
ledger admission, signed receipt with honest no-crossing semantics."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def receipt(tmp_path_factory):
    out = tmp_path_factory.mktemp("recursive")
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "run_recursive_evolution.py"),
         "--rounds", "1", "--base-seed", "8452", "--out", str(out)],
        capture_output=True, text=True, cwd=ROOT, timeout=600,
        env={**__import__("os").environ, "PYTHONPATH": "src"})
    assert proc.returncode == 0, proc.stdout[-2000:] + proc.stderr[-2000:]
    assert "RECURSIVE_EVOLUTION_PASS=true" in proc.stdout
    return {
        "stdout": proc.stdout,
        "receipt": json.loads((out / "RECURSIVE_EVOLUTION_RECEIPT.json").read_text()),
        "bundle": json.loads((out / "round-01" / "REPLAY_BUNDLE.json").read_text()),
    }


def test_round_admitted_with_replay_verification(receipt):
    rounds = receipt["receipt"]["rounds"]
    assert len(rounds) == 1 and rounds[0]["status"] == "ADMITTED"
    assert rounds[0]["replay_passed"] is True
    assert rounds[0]["replay_report"]["decisions_mismatched"] == 0
    assert receipt["receipt"]["chains_verified"] is True


def test_bundle_carries_bound_feedback_state(receipt):
    bundle = receipt["bundle"]
    assert "feedback" in bundle
    from eagle_eye.feedback import state_sha256, validate_state
    validate_state(bundle["feedback"]["state"])
    sha = state_sha256(bundle["feedback"]["state"])
    rows = bundle["chains"]["lineage"]["rows"]
    assert rows and all(
        r["body"]["candidate"]["feedback_state_sha256"] == sha for r in rows)
    assert receipt["receipt"]["rounds"][0]["feedback_state_sha256_before"] == sha


def test_ledger_evidence_recomputed_not_copied(receipt):
    """The ledger's own recompute must agree with what the receipt admitted."""
    from eagle_eye.eprocess import extract_stream_evidence, log_e_micro
    evidence = extract_stream_evidence(receipt["bundle"])
    admitted = {c["stream_id"]: c for c in receipt["receipt"]["rounds"][0]["contributions"]}
    contributing = {sid: ev for sid, ev in evidence["streams"].items()
                    if ev["contributing_look"] is not None}
    assert set(admitted) == set(contributing)
    for sid, ev in contributing.items():
        assert admitted[sid]["wins"] == ev["wins"]
        assert admitted[sid]["losses"] == ev["losses"]
        assert admitted[sid]["log_e_micro"] == log_e_micro(ev["wins"], ev["losses"])


def test_receipt_is_honest_about_crossings(receipt):
    rec = receipt["receipt"]
    assert rec["honesty"]["crossing_required_for_pass"] is False
    assert rec["external_action"] is False
    standing = rec["standing_top"]
    crossings = rec["crossings"]
    assert all(s["crossed"] == (s["cumulative_log_e_micro"] >= rec["log_threshold_micro"])
               for s in standing)
    if not crossings:
        assert "NO_STREAM_CROSSED_PROMOTION_EVIDENCE_THRESHOLD" in receipt["stdout"]


def test_feedback_state_evolved_after_round(receipt):
    r0 = receipt["receipt"]["rounds"][0]
    assert r0["feedback_state_sha256_after"] != r0["feedback_state_sha256_before"]
