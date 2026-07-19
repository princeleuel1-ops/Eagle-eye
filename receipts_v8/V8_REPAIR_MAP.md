---
type: verification_receipt
title: Eagle Eye V8 — Repair Map
timestamp: 2026-07-17
external_action: false
---

# V8 repair map

| # | Mission item | Change | Enforcing evidence |
|---|---|---|---|
| 1 | Add a separate W-transfer court without touching V7 e-process identities | `src/eagle_eye/transfer.py` introduces a distinct preregistered protocol, seed-level cluster accounting, separate NLL / CRPS streams, deterministic receipt hashing, and duplicate family/seed refusal | `tests/test_transfer.py`; `tests/test_eprocess.py` unchanged |
| 2 | Add a fixed preregistered family panel including an adversarial anti-prior adapter | `src/eagle_eye/regimes_adversarial.py` adds `original-fresh`, `independent-mixture`, and `anti-prior-metadata-shift` manifests plus deterministic adapters | `tests/test_w_transfer_replay.py` mutation `family_release`; `w-transfer` gate |
| 3 | Require a reproducible, non-vacuous champion baseline and full replay before transfer admission | `scripts/run_w_transfer_baseline.py` builds a public, explicitly synthetic test fixture; `scripts/run_w_transfer.py` hashes the explicit bundle, reruns `replay_sealed_evolution.py`, and refuses any non-`PASS_FULL_DECISION` / nonzero-mismatch source | `w-transfer-baseline` and `w-transfer` gates; `tests/test_w_transfer_baseline.py` |
| 4 | Make W-transfer fully replayable | `scripts/replay_w_transfer.py` regenerates protocol, families, worlds, registries, targets, predictions, per-case scores, cluster signs, stream trajectories, thresholds, claim outcome, and receipt id | `tests/test_w_transfer_replay.py`; `w-transfer-replay` gate |
| 5 | Keep the canonical gate additive and fail-closed | `scripts/run_all_gates.py` adds `w-transfer-baseline`, `w-transfer`, and `w-transfer-replay` after the inherited sealed benchmark/replay; PASS still depends on execution, never on a positive alien-transfer result | `make check` semantics; direct gate list in `scripts/run_all_gates.py` |
| 6 | Expose operator targets for the new mechanisms | `Makefile` adds `w-transfer-baseline`, `w-transfer`, and `w-transfer-replay` targets | `make w-transfer`; `make w-transfer-replay` |
| 7 | Preserve the wall honestly while upgrading the measurement surface | `receipts_v8/V8_HONEST_REMAINING_WALLS.md` preserves the negative W-transfer conclusion and states the exact e-process outcome without inventing a confidence interval | this receipt set |

Files added:
`src/eagle_eye/transfer.py`,
`src/eagle_eye/regimes_adversarial.py`,
`scripts/run_w_transfer.py`,
`scripts/run_w_transfer_baseline.py`,
`scripts/replay_w_transfer.py`,
`tests/test_transfer.py`,
`tests/test_w_transfer_baseline.py`,
`tests/test_w_transfer_replay.py`,
`receipts_v8/`.

Files changed:
`scripts/run_all_gates.py`,
`Makefile`,
`DOWNLOAD_MANIFEST_SHA256.txt` (regenerated).
