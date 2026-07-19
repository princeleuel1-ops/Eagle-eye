# V7 REPAIR MAP — mission item → change → enforcing test/gate

| # | Mission item | Change | Enforcing evidence |
|---|---|---|---|
| 1 | Cross-run promotion evidence must be statistical, not procedural (V6 W-promotion) | `src/eagle_eye/eprocess.py`: per-stream anytime-valid e-process; binomial mixture sign e-values in integer micro-nats; pre-registered α=0.05 threshold `2_995_732` micro-nats | `tests/test_eprocess.py` (validity enumerations, Ville battery, power battery, determinism); `recursive-evolution` gate |
| 2 | Evidence must come only from verified runs | `EProcessLedger.admit_run` refuses without a passed independent replay; re-derives per-case evidence from the revealed bundle (suite + registry rebuilt, commitments checked, `n_paired` cross-checked); refuses double admission | `test_admission_refused_without_replay_pass`; `test_ledger_evidence_recomputed_not_copied`; driver aborts on `REPLAY_FAILED`/`ADMISSION_REFUSED` |
| 3 | Same-suite dependence must not forge evidence | first-look-per-stream-per-run rule; duplicates recorded non-contributing | `extract_stream_evidence` + admission `duplicate_looks_excluded` history |
| 4 | Generation must learn from verified outcomes ("the flywheel must climb") | `src/eagle_eye/feedback.py`: signed integer FeedbackState; pure floor-bounded update from revealed lineage outcomes + ledger standing; deterministic weighted generation over the UNCHANGED whitelist | `tests/test_feedback.py` (16 tests: shape, tamper-refusal, purity, floor, steering, no-starvation) |
| 5 | The learning loop must not contaminate sealed evaluation | state consumed by run N is hash-fixed before run N's secret exists; state sha bound into generation seed and every candidate id; replay enforces `FEEDBACK_STATE_BOUND` | `test_weighted_generation_is_deterministic_and_bound_to_state`; `test_bundle_carries_bound_feedback_state`; replay feedback branch |
| 6 | The loop must be independently replayable end-to-end | `replay_sealed_evolution.py` additive branch recomputes weighted generation from the recorded state (legacy bundles: identical pre-V7 path) | `tests/test_recursive_evolution.py::test_round_admitted_with_replay_verification` (child-process replay, 0 mismatched decisions); `full-decision-replay`, `battery-fixture`, `mutation-battery` gates still green (legacy untouched) |
| 7 | The whole loop must be a canonical gate | `scripts/run_recursive_evolution.py`; Makefile `recursive-evolution`; registered in `REQUIRED_GATES` (26th gate) — PASS requires all mechanics, never a crossing | `make recursive-evolution`; `make check` |
| 8 | Honesty must be structural | receipt embeds `honesty` block (`crossing_required_for_pass: false`, claim class on crossing); `NO_STREAM_CROSSED_PROMOTION_EVIDENCE_THRESHOLD` printed when true; walls updated, not deleted | `test_receipt_is_honest_about_crossings`; `receipts_v7/V7_HONEST_REMAINING_WALLS.md` |

Files added: `src/eagle_eye/eprocess.py`, `src/eagle_eye/feedback.py`,
`scripts/run_recursive_evolution.py`, `tests/test_eprocess.py`,
`tests/test_feedback.py`, `tests/test_recursive_evolution.py`,
`receipts_v7/` (4 documents).
Files changed (all additive): `src/eagle_eye/evolution.py` (optional
`feedback_state` kwarg), `scripts/run_sealed_evolution.py` (optional kwarg +
optional bundle block), `scripts/replay_sealed_evolution.py` (feedback-aware
branch + binding check), `Makefile`, `scripts/run_all_gates.py` (26th gate),
`LOCAL_REPRODUCTION.md`, `DOWNLOAD_MANIFEST_SHA256.txt` (regenerated).
