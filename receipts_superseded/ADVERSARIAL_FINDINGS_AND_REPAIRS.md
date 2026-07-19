# Adversarial Findings and Repairs — Zenith Run

Every finding below was produced by actually executing an attack or test
against the working system, observing the failure, and repairing the root
cause. Findings are ordered chronologically.

## F1 — Closed-form t-CRPS accused wrongly; the accuser was guilty
- Attack: numerical-integration cross-check of `t_crps` (df=4, location-scale) disagreed by ~6e-4.
- Diagnosis: the closed form matched an independently hand-derived exact anchor to 3e-16; two trapezoid resolutions disagreed with each other by 1.4e-3 → the numeric check itself was under-resolved at the CDF kink and long tails.
- Repair: replaced the weak check with (a) an exact df=4 CDF closed form (`1/2 + (3/4)(s − s³/3)`), (b) an exact CRPS anchor at y=0, (c) an independent pinball/quantile-integral representation. All pass at 1e-12/5e-4.
- Class repair: every stats primitive now has at least one exact identity test, not just approximate cross-checks.

## F2 — "Pooling is overconfident in scale" was the wrong pathology
- Attack: test asserted naive pooling has smaller predictive scale than set_mt; reality showed the opposite (pooled variance absorbs between-task τ and intervention offsets).
- Diagnosis: the real pooling pathology in this domain is **location capture**: ~50 pooled prior observations drown the target's 2 observations, so the pooled posterior barely responds to target evidence (paper's anti-pattern, mechanism-level).
- Repair: test now perturbs target evidence by +1.0 log-days and asserts set_mt responds >3× more than pooling; df explosion assertion kept.

## F3 — K-extrapolation probe could not trigger (support range too wide)
- Attack: holdout `k_probe_beyond` cases with k_max=30 against declared k_range [0,24]; eligible same-class prior tasks max out at 16 → probe never exceeded support.
- Repair: validated support tightened to the range the court actually sweeps (k_range [0,12], context [0,200]); probes now exceed it and the governor abstains 2/2.

## F4 — Governor punished for correct fail-closed behavior
- Attack: `unrelated_priors` cases left the governed candidate a K=0 context (selector's top-k was all same-class; wrong-class filter emptied it); the governor abstained (correct) but the court's abstention gate counted those as standard-case abstentions and rejected the candidate.
- Repair (two roots): (1) attack subsets are now exempt from the standard-abstention count; (2) the unrelated-priors subset now forces a FULL-K wrong-class prefix so negative transfer is actually measured rather than an empty context.
- Measured result after repair: governed NLL 1.361 on wrong-class priors vs 0.798 matched — negative transfer quantified at ~0.56 nats.

## F5 — Abstention gate redefined as a promotion requirement
- Finding: raw `set_mt` (no governor) passed every scoring gate while silently predicting beyond validated K support — violating invariant 8.
- Repair: promotion now requires `out_of_support_refused` (all probes abstained). Result: only `governed_set_mt` is promotable; raw set_mt is rejected with exactly that reason. The shipped engine refuses ungoverned candidates (`attach_posterior_intelligence` raises unless candidate == governed_set_mt with a court promotion).

## F6 — Node verifier crashed on unsigned rooms in tamper tests
- Attack: posterior tamper battery used unsigned rooms; verify.mjs assumes `manifest.signature` exists → TypeError → generic error result without posterior fields.
- Repair: strengthened the attacker model instead of weakening the verifier — tampered rooms are now RE-SIGNED with an attacker's own key. The Ed25519 signature then verifies; only the posterior commitment checks catch the forgery. Both runtimes catch all five tamper classes.

## F7 — Cross-runtime float canonicalization drift (brittle B6) closed by design
- Finding: Python `json.dumps(2.0)` → "2.0" but Node re-serializes parsed 2.0 as "2" — any recomputed hash over float-bearing structures would diverge.
- Repair: (1) selector receipts and calibration receipts are float-free by construction (milli/micro integer units); (2) distribution commitments hash a `quantize_micro` transform (integer-valued floats normalize to ints; non-integers to floor(x·1e6+0.5)) implemented identically in Python, Node, and the browser panel. Locked by `test_selector_receipt_contains_no_floats`, `test_quantize_micro_cross_runtime_semantics`, and dual-runtime verification tests.

## F8 — Engineered Goodhart candidate (rejection path proven)
- Candidate: `seq_prefix_overfit` — recency decay 0.35 + interval sharpening ×0.40, tuned to development.
- Measured: best development NLL of ALL candidates (0.687 vs baseline 0.872) — genuinely attractive.
- Sealed verdict: REJECTED — permutation spread 0.37 log-units (7× tolerance) and no out-of-support refusal; holdout coverage degraded to 0.739 (vs 0.87 set_mt, 0.90 governed).
- The court receipt proves both `beneficial_candidate_promoted` and `attractive_regression_rejected` with the attractiveness condition (dev improvement) checked inside the proof itself.

## Residual attack surface (open, documented)
- Coverage band floor (0.70) did not trip for the overfit candidate (fat-tailed t intervals shrink slowly); rejection rests on permutation + support gates. A future percentile-sharpness gate would strengthen this.
- Heavy-tail (df=3) regimes are scored but have no exact oracle; misspecification is priced by NLL/CRPS only.
- The browser panel's commitment recomputation is semantically tested but not visually executed in this environment (see HONEST_REMAINING_WALLS).
