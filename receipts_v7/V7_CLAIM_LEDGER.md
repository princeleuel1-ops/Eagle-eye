# V7 CLAIM LEDGER — Recursive Sealed Evolution (delta over V6)

The V6 ledger (`receipts_v6/V6_CLAIM_LEDGER.md`) remains canonical for the
pilot spine and the merged V5 kernel; every V6 claim was re-verified by the
canonical gate on this tree. This delta ledger covers ONLY what V7 adds.
Evidence-class vocabulary unchanged.

## A. New mechanisms

| Area | Claim | Class | Evidence |
|---|---|---|---|
| E-value correctness | closed-form binomial mixture e-value: exact single-trial values, neutrality at zero evidence, monotone in wins | MECHANICALLY VERIFIED | `tests/test_eprocess.py` closed-form block |
| E-value validity | expectation EXACTLY 1 at the null boundary; ≤ 1 for all θ ≤ 1/2 (exact enumeration m ≤ 16) | MECHANICALLY VERIFIED (enumeration) / THEOREM-CONDITIONAL (general m: mixture-MLR argument) | `test_expectation_exactly_one_at_null_boundary`, `test_expectation_at_most_one_everywhere_under_null` |
| Time-uniform error control | running-wealth crossing frequency under a simulated null stays ≤ 2α (deterministic seeded battery, 300 streams × 10 runs) | SYNTHETICALLY VERIFIED (regression pin on the Ville property) | `test_ville_crossing_frequency_under_null` |
| Evidence accumulation | a true 66%-win challenger usually crosses within 10 runs — cross-run evidence PERSISTS instead of dying per run | SYNTHETICALLY VERIFIED | `test_power_under_true_advantage` |
| Ledger admission | fail-closed: refuses without a passed independent replay; refuses double admission; recomputes all evidence from the revealed bundle and aborts on any inconsistency with recorded `n_paired` | MECHANICALLY VERIFIED | `test_admission_refused_without_replay_pass`, `test_ledger_evidence_recomputed_not_copied`, `eprocess.extract_stream_evidence` hard errors |
| Within-run dependence guard | only the first sealed look per (champion, challenger) pair per run contributes | MECHANICALLY VERIFIED | `extract_stream_evidence` first-look rule + admission history `duplicate_looks_excluded` |
| Feedback state integrity | whitelist-exact shape enforced; tampering (missing key, zero weight, foreign value, non-integer) refused | MECHANICALLY VERIFIED | `tests/test_feedback.py::test_validate_rejects_tampering` |
| Feedback update | pure, integer, floor-bounded (+5 promoted / +2 near-miss / −2 blocked / +1 evidence stream); foreign diffs ignored (search space never widens) | MECHANICALLY VERIFIED | `test_update_rewards_and_penalties_with_floor`, `test_update_is_pure_and_ignores_foreign_diffs` |
| Weighted generation | deterministic; same whitelist/grids/budget/skip rules; ids bind the state sha256; state change ⇒ id change; heavy weights steer, floor prevents starvation | MECHANICALLY VERIFIED | `test_weighted_generation_*`, `test_floor_prevents_starvation` |
| Replay of feedback bundles | independent replay recomputes weighted generation bit-for-bit and enforces `FEEDBACK_STATE_BOUND` on every lineage row | MECHANICALLY VERIFIED | `tests/test_recursive_evolution.py::test_round_admitted_with_replay_verification` (child-process replay, 0 mismatches); `replay_sealed_evolution.py` feedback branch |
| Recursive loop | run → independent replay → fail-closed admission → pure learn, all rows signed; PASS requires every mechanical invariant, NEVER a crossing | MECHANICALLY VERIFIED | `recursive-evolution` gate; `tests/test_recursive_evolution.py` |
| Legacy compatibility | feedback default None ⇒ bit-identical legacy behavior; legacy bundles replay through the identical pre-V7 branch; pinned battery fixture untouched | MECHANICALLY VERIFIED | `tests/test_evolution.py`, `tests/test_replay_full_decision.py`, `battery-fixture` + `mutation-battery` gates all green on this tree |

## B. Per-run / receipt-bound findings (NOT invariants)

- Ledger standings, crossings, and per-stream log-e values belong to the
  specific bound run set (fresh CSPRNG secrets). The gate's honest common
  outcome at 3 rounds is NO crossing. Any crossing claim lives in the bound
  `RECURSIVE_EVOLUTION_RECEIPT.json`, labeled THEOREM-CONDITIONAL
  (independent synthetic case sampling), and is never promoted to a
  universal, live-data, or alien-generator claim.

## C. NOT ESTABLISHED (unchanged by V7)

Alien-generator advantage (W-transfer) · live data · production KMS/OIDC/
storage/transparency · organizational isolation · real external execution ·
external validation of ANY claim · general self-improvement beyond the
bounded, whitelisted, verified loop described here. A learning loop over a
fixed 7-parameter whitelist is NOT general self-improvement and is not
claimed as such.
