# V5 REPAIR MAP — mission item → change → enforcing evidence

Traces each Phase-2/Phase-3 mission item to its implementation and the test/
gate that enforces it. "Carried" = integrated unchanged from the verified V4
kernel and re-verified by the V5 canonical gate.

## Phase 2 — verified V4 kernel integrated into the canonical tree
Signed chains + dual-runtime verifier; Bayesian regime engine, prior registry/
selector, predictors, governor, prediction court; sealed evaluator lifecycle +
charged holdout access; evolution controller; outcome resolution; conformal;
VOI; full-decision replay + mutation battery; power analysis; parameter-shift
+ independent-generator evaluations; cockpit + 113 PNG node assets + registry;
dual-control governance; policy/posterior verification; complete `make check`.
Integrated as 7 grouped conventional commits on `agent/eagle-eye-v5-convergence`
off the reconstructed 46f6e2f baseline. Generated artifacts, caches, venvs, and
stale `latest/` dirs were NOT copied (`.gitignore` + selective staging).

## Phase 3 — pushed beyond V4

| # | Mission item | Change | Enforced by |
|---|---|---|---|
| 1 | Setup portability | preflight diagnostic + scrubbed env (Makefile, gate runner) | `tests/test_preflight.py`, `preflight` gate |
| 2 | Replay claim precision | per-run counts bound to run artifacts; no invariant prose; replay schema explicit on binding vs informational | `docs/V4_REPLAY_SCHEMA.json`, V5_CLAIM_LEDGER §C |
| 3 | Receipt coherence | single canonical `receipts_v5/`; V1–V4 preserved under `receipts_superseded/`; stale count corrected to 227/33; live docs repointed | this file + RECEIPT_STATUS_INDEX |
| 4 | Package completeness | V5 root; all members manifested; path-safe; 113 PNGs; direct-byte verify; tested reconstruction | `scripts/verify_package.py --zip`, delivery split-manifest |
| 5 | Test quality | added high-value NEGATIVE cases (cross-chain pinning, spliced row, malformed PEM, fail-closed adapters, contamination surfaced); no gate weakened | new tests below |
| 6 | Security | chain_id/run_id binding, fail-closed PEM, fixture-key labeling, fail-closed adapters, external execution false | Lane 2 review + tests |
| 7 | Operator UX | readable inspector, live controls, lifecycle strip, decomposed proof, wrapping, mobile | 20 browser checks |
| 8 | Pilot readiness | fail-closed adapter seam + PILOT_READINESS_CHECKLIST | `tests/test_adapters.py` |
| 9 | Performance/reliability | gate runtime baselines recorded; server honors EAGLE_EYE_PORT; clean startup/shutdown in browser harness | V5_GATE_RESULTS.json elapsed_s |
| 10 | Product convergence | dead controls removed-by-wiring; one legible ingest→assess→recommend→approve/shadow→verify loop | Lane 3 report |

## New V5 tests (all additive; nothing weakened)
- `tests/test_preflight.py` — 5 (clean pass, foreign PYTHONPATH surfaced,
  PYTHONHOME surfaced, strict fail-closed, non-mutation)
- `tests/test_adapters.py` — 4 (fail-closed defaults, honest status, flag-without-backend still closed)
- `tests/test_signed_chain.py` — +3 (chain_id pinning, cross-chain presentation, malformed PEM)

## Test adaptations (documented per the no-weakening rule)
None weakened. The V4→V5 changes were purely additive to tests; the only
signature change is `verify_chain` gaining optional `expected_chain_id`/
`expected_run_id` keyword args (default None = backward compatible), so every
existing caller and test passes unchanged.

## Reconstruction-integrity note
The canonical baseline was reconstructed from the pristine source snapshot that
anchored every Zenith patch since V1 (bit-for-bit patch roundtrip verified in
the V1 delivery). The V4 kernel integrated here is the independently
hash-verified archive (SHA 43645bf7…19fad). Graft onto the real
`/Users/Apple/Projects/eagle-eye-zenith` is a human step — see
INTEGRATION_INSTRUCTIONS.md.
