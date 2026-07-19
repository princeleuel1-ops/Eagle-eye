"""V7 recursive evolution driver — the self-verifying evolving loop.

One round =
  1. RUN     a full sealed-evolution benchmark (fresh CSPRNG secret, fixed
             suite commitments, charge-before-execution — machinery UNCHANGED)
             with generation routed through the current signed FeedbackState.
  2. VERIFY  the round's replay bundle with the INDEPENDENT full-decision
             replay in a separate process. A round that does not replay
             bit-for-bit is evidence of NOTHING (fail closed, loop aborts).
  3. ADMIT   the verified bundle into the cross-run e-process ledger, which
             re-derives per-case sign evidence itself from the revealed
             secret and accumulates anytime-valid promotion evidence per
             (champion, challenger) stream.
  4. LEARN   a new FeedbackState from the revealed lineage outcomes and the
             ledger standing (pure integer update, floor-bounded), sign the
             transition, and carry it into the next round's generation.

The loop therefore LEARNS ONLY FROM WHAT IT HAS PROVED. Nothing in it can
promote a challenger by itself: per-run promotion gates are untouched, and a
ledger crossing is a separate, honestly-labeled statistical evidence claim
(theorem-conditional on independent synthetic case sampling — see
receipts_v7/V7_RECURSIVE_EVOLUTION_DESIGN.md).

Exit 0 requires EVERY mechanical invariant to hold for EVERY round:
replay PASS with zero mismatched decisions, admission accepted, feedback
chain intact, generation recomputable. It NEVER requires a ledger crossing —
"no stream crossed" is an honest, common outcome at small round counts.

usage:
  PYTHONPATH=src python scripts/run_recursive_evolution.py \
      [--rounds N] [--base-seed S] [--suite-scale K] [--out DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from eagle_eye.eprocess import (  # noqa: E402
    EPROCESS_ALPHA_MICRO,
    EPROCESS_LOG_THRESHOLD_MICRO,
    EProcessLedger,
)
from eagle_eye.feedback import (  # noqa: E402
    FEEDBACK_SPEC,
    genesis_state,
    lineage_outcomes_from_bundle,
    state_sha256,
    update_state,
)
from eagle_eye.prior_registry import canonical_bytes, sha256_hex  # noqa: E402
from eagle_eye.signed_chain import SignedChain  # noqa: E402
from eagle_eye.signing import generate_demo_keypair  # noqa: E402

import run_sealed_evolution as sealed_run  # noqa: E402

RECURSIVE_SPEC = "eagle-eye-recursive-evolution/1.0"
DEFAULT_ROUNDS = 3
DEFAULT_BASE_SEED = 7100


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def independent_replay(bundle_path: Path) -> tuple[bool, dict]:
    """Run the UNMODIFIED-entry-point independent replay in a child process."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "replay_sealed_evolution.py"), str(bundle_path)],
        capture_output=True, text=True, cwd=ROOT,
        env={**__import__("os").environ, "PYTHONPATH": "src"})
    out = proc.stdout
    mismatched = None
    for line in out.splitlines():
        if line.startswith("DECISIONS_RECOMPUTED="):
            # e.g. DECISIONS_RECOMPUTED=3 MISMATCHED=0
            try:
                mismatched = int(line.rsplit("MISMATCHED=", 1)[1])
            except (IndexError, ValueError):
                mismatched = None
    passed = proc.returncode == 0 and mismatched == 0
    report = {
        "returncode": proc.returncode,
        "decisions_mismatched": mismatched,
        "stdout_sha256": sha256_hex(out.encode()),
        "tail": out.strip().splitlines()[-3:] if out.strip() else [],
    }
    return passed, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument("--base-seed", type=int, default=DEFAULT_BASE_SEED)
    parser.add_argument("--suite-scale", type=int, default=None,
                        help="forwarded to run_sealed_evolution (default: its own default)")
    parser.add_argument("--out", type=Path, default=ROOT / "artifacts" / "recursive")
    args = parser.parse_args()

    out_root: Path = args.out
    out_root.mkdir(parents=True, exist_ok=True)
    started = time.time()

    ledger = EProcessLedger(run_id="run-recursive")
    private_key, public_key = generate_demo_keypair()
    rounds_chain = SignedChain(tenant_id="tenant-demo", run_id="run-recursive",
                               chain_id="recursive-rounds",
                               private_key=private_key, public_key=public_key)

    state = genesis_state()
    rounds_report = []
    all_ok = True

    for i in range(1, args.rounds + 1):
        live_seed = args.base_seed + i
        round_dir = out_root / f"round-{i:02d}"
        state_sha_before = state_sha256(state)
        run_kwargs = {"live_seed": live_seed, "out_dir": round_dir,
                      "feedback_state": state}
        if args.suite_scale is not None:
            run_kwargs["suite_scale"] = args.suite_scale
        rc = sealed_run.main(**run_kwargs)
        bundle_path = round_dir / "REPLAY_BUNDLE.json"
        round_row: dict = {"spec": RECURSIVE_SPEC, "kind": "recursive_round",
                           "round": i, "live_seed": live_seed,
                           "run_exit_code": rc,
                           "feedback_state_sha256_before": state_sha_before}
        if rc != 0 or not bundle_path.exists():
            round_row.update({"status": "RUN_FAILED"})
            rounds_chain.append(round_row)
            rounds_report.append(round_row)
            all_ok = False
            break

        bundle_sha = sha256_file(bundle_path)
        replay_passed, replay_report = independent_replay(bundle_path)
        round_row.update({"bundle_sha256": bundle_sha,
                          "replay_passed": replay_passed,
                          "replay_report": replay_report})
        if not replay_passed:
            round_row.update({"status": "REPLAY_FAILED"})
            rounds_chain.append(round_row)
            rounds_report.append(round_row)
            all_ok = False
            break

        bundle = json.loads(bundle_path.read_text())
        # binding checks tying the round together (fail closed on any):
        fb = bundle.get("feedback")
        if fb is None or state_sha256(fb["state"]) != state_sha_before:
            round_row.update({"status": "FEEDBACK_BINDING_FAILED"})
            rounds_chain.append(round_row)
            rounds_report.append(round_row)
            all_ok = False
            break
        try:
            admission = ledger.admit_run(bundle, bundle_sha256=bundle_sha,
                                         replay_passed=replay_passed,
                                         replay_report=replay_report)
        except ValueError as exc:
            round_row.update({"status": "ADMISSION_REFUSED", "error": str(exc)})
            rounds_chain.append(round_row)
            rounds_report.append(round_row)
            all_ok = False
            break

        outcomes = lineage_outcomes_from_bundle(bundle)
        standing = ledger.standing()
        state = update_state(state, lineage_outcomes=outcomes,
                             evidence_standing=[
                                 {**s, "diff": ledger.state["streams"][s["stream_id"]]["diff"]}
                                 for s in standing])
        round_row.update({
            "status": "ADMITTED",
            "admission_row_hash": admission["row_hash"],
            "looks_seen": admission["looks_seen"],
            "looks_contributing": admission["looks_contributing"],
            "contributions": admission["contributions"],
            "ledger_state_sha256": ledger.state_sha256(),
            "feedback_state_sha256_after": state_sha256(state),
        })
        rounds_chain.append(round_row)
        rounds_report.append(round_row)

    standing = ledger.standing()
    crossings = ledger.crossings()
    chains_verified = ledger.verify_chain() and _chain_ok(rounds_chain)
    receipt = {
        "spec": RECURSIVE_SPEC,
        "feedback_spec": FEEDBACK_SPEC,
        "alpha_micro": EPROCESS_ALPHA_MICRO,
        "log_threshold_micro": EPROCESS_LOG_THRESHOLD_MICRO,
        "rounds_attempted": args.rounds,
        "rounds_completed": sum(1 for r in rounds_report if r.get("status") == "ADMITTED"),
        "rounds": rounds_report,
        "ledger_state": ledger.state,
        "ledger_state_sha256": ledger.state_sha256(),
        "standing_top": standing[:10],
        "crossings": crossings,
        "chains_verified": chains_verified,
        "external_action": False,
        "elapsed_s": round(time.time() - started, 1),
        "honesty": {
            "crossing_required_for_pass": False,
            "claim_class_on_crossing": "THEOREM-CONDITIONAL (independent synthetic case sampling; "
                                       "sealed-suite sign null); NOT an external or live-data claim",
            "per_run_promotion_gates": "UNCHANGED and binding",
        },
    }
    receipt["receipt_id"] = "recur-" + sha256_hex(canonical_bytes(receipt))[:12]
    (out_root / "RECURSIVE_EVOLUTION_RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True))

    ok = (all_ok
          and receipt["rounds_completed"] == args.rounds
          and chains_verified)
    print(f"ROUNDS_COMPLETED={receipt['rounds_completed']}/{args.rounds}")
    print(f"REPLAYS_ALL_PASSED={str(all(r.get('replay_passed', False) for r in rounds_report)).lower()}")
    print(f"RUNS_ADMITTED={len(ledger.state['admitted_runs'])}")
    print(f"EVIDENCE_STREAMS={len(ledger.state['streams'])}")
    if standing:
        top = standing[0]
        print(f"TOP_STREAM_LOG_E_MICRO={top['cumulative_log_e_micro']} ({json.dumps(top['diff'], sort_keys=True)})")
    print(f"LEDGER_CROSSINGS={len(crossings)}")
    if not crossings:
        print("NO_STREAM_CROSSED_PROMOTION_EVIDENCE_THRESHOLD")
    print(f"CHAINS_VERIFIED={str(chains_verified).lower()}")
    print(f"FEEDBACK_STATE_FINAL_SHA256={state_sha256(state)}")
    print(f"RECEIPT_ID={receipt['receipt_id']}")
    print(f"RECURSIVE_EVOLUTION_PASS={str(ok).lower()}")
    return 0 if ok else 1


def _chain_ok(chain: SignedChain) -> bool:
    from eagle_eye.signed_chain import verify_chain
    registry = {"trusted_signers": [{"key_id": chain.signer_key_id,
                                     "public_key_pem": chain.public_key.decode()}]}
    report = verify_chain(chain.rows, chain.anchor(), registry,
                          expected_tenant=chain.tenant_id,
                          expected_chain_id=chain.chain_id,
                          expected_run_id=chain.run_id)
    return bool(report.get("verified", False))


if __name__ == "__main__":
    raise SystemExit(main())
