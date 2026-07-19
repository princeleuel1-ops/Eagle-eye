# Source and Claim Ledger — Zenith Run

Every load-bearing input this run relied on, with how it was verified.

| Source | What was taken | Verification |
|---|---|---|
| Drive folder 1NFbu7wNrWdZOaP3x44q85OSkRVkMn4xn | 7 payload zips + 4 instruction files | all 10 SHA-256 hashes match MANIFEST_SHA256.txt (VERIFIED) |
| FINAL_VERIFICATION.json (package) | expected state: 54 tests, verifier parity, court pass | reproduced by execution before any change (VERIFIED) |
| project/ source @ 46f6e2f | all 14 modules read first-hand; contracts extracted | line-level inspection; behavior confirmed by running gates |
| arXiv:2606.20538v1 + official code snapshot | mechanism: λ→w_k→y hierarchy; prefix format; oracle-KL evaluation; pitfalls (K-cliff 0.0014→0.031; ERA5 OOD val −2.06→test +7.13; pooling ruled out; permutation sensitivity 0.005±0.004) | paper text + code traced by analyst lane; digest at analysis/PAPER_DIGEST.md with file/function citations |
| mission/00_ONE_MISSION.md, PAPER_MECHANISM_AND_PROJECT_MAP.md, HYPERAGENT_MASTER_BUILD_PROMPT.md | binding architecture (registry/selector/compiler/candidates/court/governor/evidence/UI), promotion criteria, boundaries | read in full; requirements cross-checked in STRATEGY digest |
| strategy/ corpus | context only; scope explicitly NOT expanded to XPRIZE/Docklight product surface | digest at analysis/STRATEGY_DIGEST.md; conflict resolution documented (mission docs govern) |
| project/docs/GAP_REGISTER.md | open-gap trust anchor | consulted; posterior work recorded as new slice receipt |

Claim-status vocabulary used across receipts: VERIFIED (executed and checked here),
MEASURED (numeric result from executed benchmark), IMPLEMENTED_NOT_EXECUTED,
INFERRED, ASSUMED (labeled at point of use), BLOCKED, REJECTED.

Key labeled assumptions (all carried into code/tests, none silent):
- A1 disruption_class + lane/region correlate with hidden regime (falsified-by: unrelated_priors + adversarial-similar subsets; measured penalty recorded)
- A2 log-delay observations are exchangeable within a task given θ_i (generator-true; live data would need residual checks)
- A3 recovery multiplier fixed estimate (documented in predictors._recovery_stats; wall W5)
- A4 synthetic calibration transfers only as far as the generator is faithful (wall W2)
