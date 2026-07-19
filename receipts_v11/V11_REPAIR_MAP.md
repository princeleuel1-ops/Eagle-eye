# V11 REPAIR MAP
| # | Item | Change | Evidence |
|---|---|---|---|
| 1 | Configuration must never equal trust | strict custody ladder; CONFIGURED_UNVERIFIED trusts nothing | ladder tests; gate stages 1-3 |
| 2 | VERIFIED only by real round-trip | nonce → remote sign → local verify protocol; content-hashed proofs; 1h expiry | protocol tests; gate stage 4-6 |
| 3 | Production signing gated | require_production_custody: VERIFIED ∧ production class; local refused BY CLASS | interlock tests; gate stage 7 |
| 4 | Identity mirrors custody | OIDC ladder + round-trip via unchanged IdentityVerifier | oidc tests; gate 9-11 |
| 5 | Canonical gate | custody-rehearsal = required gate 32 | make check |
| 6 | Operator ceremony | CUSTODY_ACTIVATION_RUNBOOK.md (KMS + OIDC + abort) | runbook shipped |
Files added: src/eagle_eye/custody.py, scripts/run_custody_rehearsal.py,
tests/test_custody.py, receipts_v11/ (5 docs). Changed (additive): Makefile,
scripts/run_all_gates.py (gate 32), LOCAL_REPRODUCTION.md, manifest.
