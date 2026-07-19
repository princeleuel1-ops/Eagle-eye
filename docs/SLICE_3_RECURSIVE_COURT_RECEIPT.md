---
type: verification_receipt
title: Eagle Eye Zenith Slice 3 — Recursive Benchmark Court
timestamp: 2026-07-12
---

# Executable claim

Eagle Eye can evaluate a proposed mutation against explicit development, hidden-holdout, safety, calibration, latency, and cost gates; promote a beneficial candidate; reject an attractive but harmful candidate; and issue deterministic receipts without executing an external production change.

# Benchmark

- Name: `EEFB-v0.1`
- Specification: `benchmarks/eefb-v0.1.json`
- Specification SHA-256: `7421c6e507492a8e43c55a8071673d7552a76e14132144ff12a533d81452ee17`
- Court receipt: `court-2a34f3754ae4`
- Data authority: authorized synthetic benchmark fixture

# Promotion case

`evidence-aware-ranking-v2`

| Metric | Baseline | Candidate |
|---|---:|---:|
| Development accuracy | 0.72 | 0.84 |
| Holdout accuracy | 0.70 | 0.81 |
| Safety | 1.00 | 1.00 |
| Calibration error | 0.18 | 0.12 |
| Latency | 180 ms | 195 ms |
| Cost | $0.040 | $0.045 |

Decision: `promote`

All promotion gates pass. Promotion still requires human approval; the fixture does not mutate production.

Receipt: `mutation-14241a98a6c6`

# Rejection case

`overfit-fast-route-v9`

| Metric | Baseline | Candidate |
|---|---:|---:|
| Development accuracy | 0.72 | 0.96 |
| Holdout accuracy | 0.70 | 0.61 |
| Safety | 1.00 | 0.92 |
| Calibration error | 0.18 | 0.27 |
| Latency | 180 ms | 120 ms |
| Cost | $0.040 | $0.020 |

Although the candidate has the highest development score, lowest latency, and lowest cost, it is rejected for:

- `holdout_regression`
- `safety_regression`
- `calibration_regression`

Receipt: `mutation-f3ee35bb5c8a`

# Required recursive proofs

```text
BENEFICIAL_MUTATION_PROMOTED=true
HARMFUL_MUTATION_REJECTED=true
```

# Product integration

`/api/benchmark` exposes the generated court receipt to the local command surface. The frontend displays both decisions, metric deltas, rejection reasons, and receipt IDs.

Semantic gate:

```text
HAS_RECURSIVE_COURT=true
```

Browser QA:

- promote/reject cards visible;
- outcomes distinguishable without relying solely on color;
- metrics and reasons legible;
- no console messages;
- no JavaScript errors.

# Full gate

```text
13 passed
SIGNATURE_VERIFIED=true
NODE_EVIDENCE_ROOM_VERIFIED=true
BENEFICIAL_MUTATION_PROMOTED=true
HARMFUL_MUTATION_REJECTED=true
HAS_RECURSIVE_COURT=true
EAGLE_EYE_ZENITH_CHECK_PASS
```

# Brittle point

EEFB-v0.1 currently consumes declared synthetic metric values. It proves the promotion mechanism but not yet that metrics were derived from sealed hidden datasets. The next hardening step must bind metric production to versioned cases, evaluator code, dataset hashes, contamination checks, and independently computed results.
