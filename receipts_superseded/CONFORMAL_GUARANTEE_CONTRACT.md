# Conformal Guarantee Contract (eagle-eye-conformal/1.0)

Method: split conformal on scale-normalized absolute residuals |y-loc|/scale (log-delay),
quantile rule = order statistic ceil((n+1)*coverage) of calibration scores.

GUARANTEE_ACTIVE      finite-sample marginal coverage >= target, valid under exchangeability
                      of calibration and use-time nonconformity scores. Proven empirically:
                      exchangeable case 200-cal/400-fresh coverage >= 0.78 (test-locked);
                      distribution-free under t3 heavy tails (test-locked).
GUARANTEE_CONDITIONAL weighted variant only; assumptions recorded verbatim: weights must be
                      true density ratios; the shift score is a heuristic, NOT a validated
                      density ratio. Never presented as unconditional.
GUARANTEE_SUSPENDED_SHIFT / _LOW_EFFECTIVE_SAMPLE / _CONTAMINATION / _NOT_APPLICABLE
                      fail-closed states. Suspension preserves the last valid calibration
                      receipt hash and instructs recalibration on an eligible regime sample.
                      No widening is applied without methodological justification; unsupported
                      precision is rejected rather than decorated.

Explicitly NOT claimed: coverage under arbitrary distribution shift.
Executed evidence: 4 ACTIVE cycles then 2 SUSPENDED_SHIFT cycles exactly at the 2025-07
regime boundary; sharpened-predictor coverage damage demonstrated (test-locked);
subgroup coverage reported per regime/subset in CONFORMAL_EVALUATION_RESULTS.json.
