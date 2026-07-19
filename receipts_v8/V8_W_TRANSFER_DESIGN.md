---
type: verification_receipt
title: Eagle Eye V8 — W-Transfer Design
timestamp: 2026-07-17
external_action: false
---

# Scope

V8 adds an additive, independently replayable W-transfer court on top of the
verified V7 tree. The V7 in-family feedback harness, e-process ledger, and
sealed-evolution bundle schema stay intact. Nothing here enables external
execution; `external_action=false`.

# Instrument

- Preregistered protocol: fixed family panel, fixed seed list, fixed target
  plan, fixed Bonferroni alpha over every preregistered family x metric stream,
  deterministic protocol hash.
- Family panel:
  `original-fresh` — fresh original-family transfer reference.
  `independent-mixture` — structurally independent Gamma-mixture family.
  `anti-prior-metadata-shift` — adversarial metadata relabeling adapter that
  keeps the original outcome generator but makes visible similarity metadata
  misleading.
- Statistical unit: one world/seed. Per-case NLL and CRPS differences are
  summed inside a seed; the seed-level sign, not the case count, advances the
  e-process.
- Streams: separate anytime-valid sign e-processes for NLL and CRPS, with
  stream identity bound to protocol hash, family id, family release, metric,
  champion config hash, and baseline release.
- Replay: `scripts/replay_w_transfer.py` independently regenerates protocol,
  family manifests, every world, registry, target, prediction, per-case score,
  seed-level cluster sign, stream trajectory, threshold, crossing index, claim
  outcome, and receipt id; any mutation, omission, or reordering fails closed.

# Gate semantics

- `scripts/run_w_transfer_baseline.py` builds a deterministic, non-vacuous V7
  source bundle at full suite scale using a public, explicitly labeled
  `test_fixture` evaluator secret. This exists only to make the V8 mechanism
  court reproducible; it is not independent holdout or external evidence.
- `scripts/run_w_transfer.py` requires an explicit `--champion-bundle` path.
- It hashes the champion bundle, reruns `replay_sealed_evolution.py` in a child
  process, and refuses admission unless that replay returns exit 0 with
  `PASS_FULL_DECISION` and `MISMATCHED=0`.
- Gate PASS requires replay integrity, protocol completeness, trust /
  calibration / abstention checks, and transfer-chain / receipt integrity.
- Gate PASS does NOT require positive alien-transfer evidence.
- Headline output is exact:
  `ALIEN_TRANSFER_EVIDENCE_EARNED` or `NO_ALIEN_TRANSFER_EVIDENCE_EARNED`.

# Evidence classes

- Protocol hashing, manifest validation, duplicate seed refusal, chain
  integrity, receipt hashing, and full replay are MECHANICALLY VERIFIED.
- The baseline and family-panel outcomes are SYNTHETICALLY VERIFIED only.
- Any stream crossing is THEOREM-CONDITIONAL on the preregistered seed-level
  sign null and the synthetic generator assumptions.
- EXTERNALLY VALIDATED: nothing.
