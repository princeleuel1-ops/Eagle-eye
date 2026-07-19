---
type: verification_receipt
title: Eagle Eye V8 — Claim Ledger Delta
timestamp: 2026-07-17
external_action: false
---

# V8 claim ledger

This is a delta over `receipts_v7/V7_CLAIM_LEDGER.md`. V7 remains canonical for
the recursive feedback harness and in-family e-process promotion evidence.

## New mechanisms

| Area | Claim | Class | Evidence |
|---|---|---|---|
| Protocol freeze | fixed family panel, seed list, target plan, Bonferroni alpha, deterministic protocol hash | MECHANICALLY VERIFIED | `tests/test_transfer.py::test_protocol_hash_refuses_alpha_and_metric_substitution`; `scripts/replay_w_transfer.py` |
| Family binding | family manifests bind release, descriptors, schema release, structural parent, and source commitment; forged release fails replay | MECHANICALLY VERIFIED | `tests/test_w_transfer_replay.py` mutation `family_release` |
| Statistical unit discipline | one world/seed is the trial; per-case correlation is collapsed into per-seed cluster sums before sign accounting | MECHANICALLY VERIFIED | `tests/test_transfer.py::test_cluster_accounting_is_seed_level_and_order_invariant` |
| Stream identity | NLL and CRPS use separate stream ids bound to protocol + family + release + metric + champion config hash + baseline release | MECHANICALLY VERIFIED | `tests/test_transfer.py::test_stream_ids_bind_family_metric_and_baseline_release` |
| Duplicate refusal | duplicate family/seed admission is rejected fail-closed | MECHANICALLY VERIFIED | `tests/test_transfer.py::test_duplicate_seed_admission_is_refused` |
| Score hygiene | nonfinite score payloads are rejected fail-closed | MECHANICALLY VERIFIED | `tests/test_transfer.py::test_nonfinite_scores_are_refused` |
| Full transfer replay | protocol, worlds, registries, targets, predictions, per-case scores, cluster signs, stream trajectories, thresholds, claim outcome, and receipt id are independently regenerated | MECHANICALLY VERIFIED | `tests/test_w_transfer_replay.py`; `w-transfer-replay` gate |
| Non-vacuous baseline fixture | a public, deterministic test-fixture secret builds a full-scale V7 source bundle whose replay has at least one recomputed decision and zero mismatches | MECHANICALLY VERIFIED; SYNTHETIC FIXTURE only | `tests/test_w_transfer_baseline.py`; `w-transfer-baseline` gate |
| Mutation battery | family id/release/source commitment, duplicate/missing/reordered seeds, registry release, deleted/duplicated/reindexed cases, champion/baseline substitution, observation/truth/score/cluster sign/claim, deleted family, truncated history, crossing index, and receipt id mutations all fail replay | MECHANICALLY VERIFIED | `tests/test_w_transfer_replay.py` |
| Family-panel execution | the W-transfer court runs the preregistered family panel and records complete per-case evidence, not samples | SYNTHETICALLY VERIFIED | `w-transfer` gate |

## Honest result discipline

- The mechanism gate is about integrity and honest measurement, not a forced
  positive result.
- `NO_ALIEN_TRANSFER_EVIDENCE_EARNED` is a valid PASS outcome.
- Any positive alien-transfer claim would be THEOREM-CONDITIONAL and
  SYNTHETICALLY VERIFIED, never external.

## Boundary

EXTERNALLY VALIDATED: nothing. `external_action=false`.
