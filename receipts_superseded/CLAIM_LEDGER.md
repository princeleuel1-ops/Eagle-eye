# Claim Ledger — Post-Audit Repaired Candidate (v2)

Evidence classes: MECHANICALLY VERIFIED (MV) | SYNTHETICALLY VERIFIED (SV) | THEOREM-CONDITIONAL (TC) | EXTERNALLY VALIDATED (EV) | NOT ESTABLISHED (NE)

| Claim | Class |
|---|---|
| 184/184 tests pass; full gate chain green; external_execution=false enforced | MV |
| Registry growth carries ONLY recorded observed fields; unknowns stay None; fail-closed ledger membership + chain check | MV |
| Snapshot identity recomputed on every registry mutation; candidate ids snapshot-bound (no cross-registry collisions) | MV |
| Ed25519-signed anchored chains (outcomes, lineage, evaluator); rewrite/rehash, truncation, reorder, signer substitution, wrong tenant, forged anchor ALL rejected in Python AND Node | MV |
| Evaluator boundary: no holdout rows/labels/seeds in candidate domain; commit-reveal seed commitment; one-shot nonces; budget; looks derived from signed ledger; champion charged | MV (API level); organizational independence NE |
| Promotion decision rule: precommitted paired one-sided test, Bonferroni alpha_total/max_looks per look, full stats receipt (hypothesis, t, CI, alpha ledger, n, stopping rule, assumptions) | MV (procedure); normality of mean diff TC (CLT, n>=30 enforced) |
| Conformal: finite-sample coverage under exchangeability; ceil rounding conservative; calibration/evaluation disjoint; recalibration on champion OR registry change; weighted path REMOVED | TC (guarantee) + MV (mechanics) + SV (coverage 0.78+ observed) |
| Off-policy: propensities recomputed from authenticated policy records; forged claims -> NOT_IDENTIFIABLE; overlap/ESS/concentration measured from ledger; sensitivity to unobserved confounding | MV (checks); causal identifiability IDENTIFIABLE_UNDER_STATED_ASSUMPTIONS at best; sensitivity NE |
| 6/6 cycles completed at seeds 550 and 999; 17 rejections; NO_CHALLENGER_EARNED_PROMOTION (gates NOT lowered) | SV |
| Trust/calibration/shift-gate rejection of dev-attractive challengers | MV (deterministic gate-branch tests) |
| Integrity replay from sealed bundle (commit-reveal, suite rebuild, 3 chains x 2 runtimes, ledger-derived looks) | MV |
| Full decision recomputation replay (re-running every evaluation from bundle) | NE (declared wall) |
| Cross-generator evaluation | NOT EXECUTED (single generator exists) |
| Any live/category-superiority claim | NE — all results are synthetic |
