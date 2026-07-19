---
type: verification_receipt
title: Eagle Eye Zenith Slice 4 — Hash-Bound Measured EEFB
timestamp: 2026-07-12
---

# Executable claim

The recursive benchmark court derives accuracy, safety, and calibration metrics from versioned case-level predictions rather than accepting those metrics as manually declared values.

# Benchmark

- Name: `EEFB-v0.2-measured`
- Development cases: 10 authorized synthetic cases
- Holdout cases: 10 authorized synthetic cases
- Contamination detected: false
- Court receipt: `court-05be9d298e39`

# Hash-bound inputs

```text
DEVELOPMENT_SHA256=a1eb8ecfb0676a049c40d0885d16040947e3df523be055a3c4daa858eada2097
HOLDOUT_SHA256=24848747060073ab1128c742f0bbb66a7257ef397cc6fc10a8b53bd9ce0ef07c
```

Each candidate prediction file also has a SHA-256 embedded in the generated measured benchmark specification.

# Contamination controls

The evaluator rejects:

- overlapping case IDs across development and holdout;
- identical case content under different IDs across the two splits;
- missing predictions;
- extra predictions;
- duplicate prediction IDs;
- probabilities outside `[0, 1]`.

A dedicated test supplies the same case to both splits and verifies that evaluation raises `benchmark contamination detected`.

# Computed metrics

For every candidate, the evaluator computes:

- development accuracy;
- holdout accuracy;
- holdout safety score on safety-critical cases;
- holdout mean squared probability error as the current calibration error;
- exact case counts.

Latency and cost remain candidate-run metadata in this local fixture and are not yet independently measured.

# Full gate

```text
16 passed
BENCHMARK=EEFB-v0.2-measured
DEVELOPMENT_CASES=10
HOLDOUT_CASES=10
CONTAMINATION_DETECTED=false
BENEFICIAL_MUTATION_PROMOTED=true
HARMFUL_MUTATION_REJECTED=true
COURT_RECEIPT_ID=court-05be9d298e39
EAGLE_EYE_ZENITH_CHECK_PASS
```

# Honest limitations

- Cases and predictions are synthetic and stored in the repository; the holdout is logically separated and hash-bound but not secret from a developer with repository access.
- Ten cases per split prove the harness contract, not statistical power or real-world generalization.
- Latency and cost are metadata rather than profiler/billing outputs.
- Safety labels are fixture labels, not independently adjudicated customer outcomes.
- A production benchmark requires access-controlled rotating holdouts, independent case adjudication, confidence intervals, contamination audits, and customer-derived outcomes.
