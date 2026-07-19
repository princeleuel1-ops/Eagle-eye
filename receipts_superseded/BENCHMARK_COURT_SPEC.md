# Prediction Court Specification (eagle-eye-prediction-court/1.0)

## Suites (sealed before scoring; content-hashed; truth in sibling files)
- development: seed 11 — 28 IID cases across 3 disruption classes, n_target ∈ {1,2,4}
- holdout: seed 202607 — 46 cases:
  - iid (18) · temporal_ood (8: post-regime-shift targets, pre-shift-dominated priors)
  - heavy_tail (8: df=3 regime) · scarcity (8: n_target ∈ {0,1})
  - k_probe_beyond (2: k_max 30 > validated 12 — REQUIRES abstention)
  - unrelated_priors (2: forced full-K wrong-class prefix — negative transfer, informational)
- contamination: id overlap, content fingerprints, world-seed distinctness (any hit → detected)
- leakage battery: future-task compile refusal · foreign-tenant compile refusal · selector future/foreign exclusion (all must be defended)

## Metrics (per candidate, holdout unless noted)
NLL and CRPS on log-delay (uniform monotone transform; proper-scoring comparisons valid) ·
coverage@80 + interval width · Brier for P(delay>14d) and stockout ·
KL-to-exact-hierarchical-oracle (deterministic quadrature; normal regimes only) ·
intervention regret in expected days (exact truth expectations) ·
permutation spread (6 deterministic shuffles, max Δ median log-delay) ·
subset means (temporal_ood, heavy_tail, scarcity, unrelated) · latency ms (measured, excluded from receipt id)

## Promotion rule (AND-chain vs no_prefix baseline)
proper_scoring_improved (NLL and CRPS) ∧ calibration_acceptable (coverage@80 ∈ [0.70,0.92]) ∧
temporal_ood_non_worse (0 nats tolerance) ∧ leakage_defended ∧ no_contamination ∧
permutation_within_tolerance (≤0.05) ∧ no_standard_abstention ∧ out_of_support_refused (all probes) ∧
latency_within_budget (≤50 ms) ∧ external_execution_false

## Receipt
Deterministic id: pcourt-sha256(canonical(spec, suite hashes, registry hash, contamination,
leakage, latency-stripped evaluations, decisions))[:12] — identical across re-runs (tested).
Proofs must include: beneficial_candidate_promoted ∧ attractive_regression_rejected, where
"attractive" is verified inside the proof (rejected candidate improved development NLL vs baseline).
