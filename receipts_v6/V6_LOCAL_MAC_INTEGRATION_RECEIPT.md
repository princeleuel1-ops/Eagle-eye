---
type: verification-receipt
title: Eagle Eye Zenith V6 Local macOS Integration Receipt
description: Independent audit, repair, and verification of the Fable V6 Pilot Forge handoff against the actual merged V5 repository.
tags: [eagle-eye, v6, macos, integration, verification]
timestamp: 2026-07-14T20:13:23-04:00
---

# Eagle Eye Zenith V6 — Local macOS Integration Receipt

## Authoritative base

- repository: `/Users/Apple/Projects/eagle-eye-zenith`
- actual merged V5 main: `e508b0e1f271de4732b21cab9b34c732f6d453f8`
- actual V5 tree: `a88444cecb26f313b9d4a79cc9fe0756144104fb`
- corrected V6 branch: `agent/eagle-eye-v6-local-verified`

## Intake integrity

- V6 source archive SHA-256: `e127eb9ae7fb5470a2007b21bd84aeaaf9ddd388e564b2a10d59295e03ebf0ea`
- source archive bytes: `123863494`
- members: `320`
- source manifest: `319` entries, zero missing/mismatched, `113` PNGs
- V6 bundle SHA-256: `e075844b7f7829777d8bdd3b7df2b8dcb59dd0580de42cc8140db52eb193c2ec`
- all source/bundle part hashes matched the delivered V6 manifest
- all 29 locally present delivery evidence/patch hashes matched

## Delivery defects found locally

1. The delivered 11-patch series does not apply to actual merged V5 `e508b0e1`. Patch 1 tries to reapply local V5 corrections already present and fails on `.gitignore`, `LOCAL_REPRODUCTION.md`, and `scripts/run_all_gates.py`.
2. A clean macOS run failed because the evaluator placed its AF_UNIX socket directly under the OS-managed temporary root and attempted to chmod that root.
3. Repeated testing exposed a rare unbounded Student-t synthetic sample that overflowed `timedelta` after exponentiation.
4. The delivered receipt claimed 312 tests; local collection before the added regression contained 313. The repaired branch contains 314 tests across 40 test files.

## Local repairs

- rooted the branch directly in actual V5 main instead of the reconstructed patch baseline
- moved evaluator sockets into a short per-user temp directory and added ownership verification
- bounded physically meaningless extreme synthetic log-duration tails before `exp`/`timedelta`
- added `tests/test_regime_extreme_tail.py`
- updated live test-count documentation and package hashes

## Executed verification

Fresh repaired extraction and actual-rooted worktree both returned:

- `EAGLE_EYE_ZENITH_CHECK_PASS`
- `25/25` gates
- `314` tests across `40` files
- mutation battery `19/19`
- failure court `39/39`
- full-decision replay: `1` recomputed, `0` mismatched, `PASS_FULL_DECISION`
- pilot smoke: pass
- desktop/mobile pilot browser: pass
- zero JavaScript errors
- zero unexpected failed requests
- package verify: zero missing/mismatched, `113` PNGs

## Boundary

This proves a local synthetic pilot candidate. Live data, production KMS/HSM, production OIDC, organizational evaluator isolation, durable external transparency, real external execution, and external validation remain not established. No remote push or production deployment was performed.
