# V4 REPAIR MAP — audit blocker → repair → evidence

Every non-negotiable blocker from EAGLE_EYE_ZENITH_FABLE_V3_AUDIT_2026-07-13,
the exact repair, the files changed, and the test/gate that now enforces it.

## 1. Sealed-evaluator lifecycle
- **Defect:** secret derived as `evaluator-secret-{live_seed}-{code_revision}`
  (reconstructable from public metadata → suites rebuildable pre-run); no
  lifecycle; reveal possible at any time.
- **Repair:** `provision_evaluator_secret()` (CSPRNG, 256-bit) as the explicit
  trusted boundary; commitment = sha256(canonical({secret, provenance}));
  irreversible INITIALIZED→EVALUATING→FINALIZED→REVEALABLE with a signed
  FINALIZED ledger row; `reveal_for_replay()` hard-fails before FINALIZED; no
  looks after finalize; suite content commitments (hashes) published at
  construction, BEFORE any look. In-process custody labeled non-production.
- **Files:** `src/eagle_eye/sealed_evaluator.py`, `scripts/run_sealed_evolution.py`
- **Evidence:** `tests/test_evaluator_lifecycle.py` (7 tests, incl. required
  early-reveal negative test + derived-pattern regression grep); replay checks
  LIFECYCLE_AT_REVEAL / LIFECYCLE_FINALIZED_ONCE / LIFECYCLE_NO_LOOKS_AFTER_FINALIZE.

## 2. Charge every holdout access before execution
- **Defect:** ledger row appended only on success → exceptions gave free
  (unaccounted) holdout exposure; fresh nonces allowed unlimited failed probes.
- **Repair:** signed CHARGE row appended atomically BEFORE candidate code
  runs; linked RESULT row with terminal status SUCCEEDED/FAILED/TIMED_OUT/
  REJECTED; looks and alpha derived from CHARGE rows (failures burn alpha);
  final-audit one-shot consumed at charge time; candidates receive deep
  copies of compiled contexts; malformed responses (missing 'interventions'
  key) raise instead of masquerading as abstention.
- **Files:** `src/eagle_eye/sealed_evaluator.py`, `src/eagle_eye/prediction_court.py`
- **Evidence:** `tests/test_charged_access.py` — includes the REQUIRED probe:
  capture-and-raise ×3 with 3 nonces → LOOKS_SPENT=3, 3 charge rows, 3
  terminally FAILED result rows, zero target-truth leakage (verified against
  the rebuilt suite's actual truth values); plus timeout, budget-exhaustion-
  by-failures, pre-charge nonce refusal, malformed response, failed final audit.

## 3. Real full-decision replay
- **Defect:** V3 replay recomputed selected paired-statistic fields only.
- **Repair:** complete decision-state replay (`scripts/replay_sealed_evolution.py`):
  commit-reveal + lifecycle; suite counts/content-hashes/truth-hashes/seeds vs
  PRE-RUN commitments; base/per-growth/final registry manifests; grown tasks
  via shared pure `build_grown_task`; live-world targets, champion prediction
  blocks bit-for-bit via shared `commit_cycle_prediction` (new
  `src/eagle_eye/flywheel.py`); prediction ids + distribution commitments;
  acting-policy draws + propensities; resolutions re-executed through a fresh
  PredictionLedger (hash-chain equality); candidate regeneration via pure
  `generate_candidates`; snapshot ids via pure `snapshot_identity`; dev
  pre-screen NLLs (challenger AND champion, both now bound in lineage rows);
  sealed-look aggregate + statistics + alpha recompute; gate states/reasons
  via the SAME pure `apply_promotion_gates`; final-audit recompute; 1:1
  mappings (charge↔result, SUCCEEDED↔lineage, outcomes↔resolutions) where
  missing/duplicate/extra/unmapped rows fail. Vacuous runs print
  REPLAY_RESULT=VACUOUS_INTEGRITY_ONLY and are never called full replay.
- **Schema:** `docs/V4_REPLAY_SCHEMA.json` classifies every bundle field
  BINDING_AND_VERIFIED vs INFORMATIONAL_NOT_VERIFIED.
- **Battery:** `scripts/replay_mutation_battery.py` — 19 mutations covering
  every audit-listed class (incl. candidate id, snapshot id, registry binding,
  alpha fields, aggregate metrics, final-audit values, lineage state/reasons,
  cycle cutoffs, live_world, policy_registry, resolutions, run seed, final
  registry manifest) → all nonzero; in-chain mutations are caught first by
  Ed25519 signature verification (defense-in-depth, catch-point recorded).
- **Non-vacuous CLI fixture:** `tests/test_replay_cli_end_to_end.py`
  (precommitted secret fx1 provably spends looks; battery-fixture gate in
  make check regenerates it deterministically).
- **Files also changed for bindings:** `src/eagle_eye/evolution.py` (pure
  gates/candidates/snapshot; lineage rows carry dev_nll_champion_micro,
  evaluator_charge_hash, terminal status, evaluator_version),
  `src/eagle_eye/outcome_resolution.py` (pure build_grown_task).

## 4. Version and dependency provenance
- **Repair:** single imported `EVALUATOR_VERSION` ("sealed-evaluator/4.0")
  everywhere; `src/eagle_eye/provenance.py` (lock digest fail-closed — never
  NOT_AVAILABLE; exact-pin parser; running-env verifier);
  `environment/requirements-lock.txt` generated from a real pip resolution;
  `make setup` installs the exact audited set and runs pip check + lock verify.
- **Evidence:** `tests/test_provenance.py`,
  `tests/test_evaluator_lifecycle.py::test_single_evaluator_version_constant`,
  gates `dependency-lock` + `pip-check`.

## 5. Cross-generator claim
- **Repair:** claim WITHDRAWN; script replaced by honest pair:
  `scripts/run_parameter_shift_eval.py` (IN_FAMILY label, signed champion
  config from the bundle, ORIGINAL registry + shifted targets, NLL+CRPS+
  coverage, 12 precommitted seeds, per-seed paired CIs) and
  `scripts/run_independent_generator_eval.py` + `src/eagle_eye/regimes_independent.py`
  (structurally independent family, 100 precommitted seeds, cluster-robust
  CIs, failure rates). `scripts/run_cross_generator.py` is now a withdrawal
  shim (exit 2).
- **Findings (honest):** in-family NLL transfer ESTABLISHED; in-family CRPS
  transfer NOT ESTABLISHED; independent-generator advantage NOT ESTABLISHED
  (CI straddles zero); calibration held in band under both (gated trust
  property). Exit codes gate PROTOCOL integrity + calibration, never the
  transfer direction — findings are recorded, not forced.

## 6. "Power tripled" claim
- **Repair:** claim WITHDRAWN. `build_holdout_suite(scale=k)` now replicates
  the EXACT stratum plan with independent case resampling (disjoint
  case-index blocks) — V3's n_target_obs increments removed.
  `scripts/power_analysis.py` measures Type-I and power of the EXACT
  production rule (shared `paired_test_from_diffs`) with planted deltas over
  an empirical null, iid + replica-block bootstrap (shared-world dependence),
  degenerate single-block mode excluded.
- **Evidence:** `tests/test_suite_scale.py`; POWER_ANALYSIS.json gate.

## 7. Complete package
- **Repair:** `scripts/build_package.py` + `scripts/verify_package.py`:
  internal root EAGLE_EYE_ZENITH_FABLE_HANDOFF_V4; all 113 PNGs included and
  count-enforced; every member manifested; no unmanifested payloads; no
  symlinks/absolute/traversal paths; manifest passes from clean extraction
  (--tree gate inside make check); outer zip SHA-256 recorded in the delivery
  receipt (outside the archive, since a file cannot contain its own hash).

## 8. Live cockpit
- **Defect confirmed:** `evolution.js` read `rej.lineage_hash` and
  `promo.hold_nll_micro` — neither exists in the lineage-row body stored by
  V3 state.json → TypeError → "panel unavailable".
- **Repair:** versioned contract (`docs/frontend-state-contract-4.0.md`,
  state_schema_version evolution-state/4.0); state.json now merges
  `lineage_hash` into last_promotion/last_rejection; panel rewritten with
  null-safe accessors + fallbacks and a contract chip; server honors
  EAGLE_EYE_PORT; favicon added (kills the auto-request 404).
- **Evidence:** `verifier/dom_contract_test.mjs` (12 checks incl. the exact
  V3 crash regression) + REAL browser workflow
  `scripts/browser_verification.py` (15 checks, zero JS errors, zero failed
  requests, screenshot receipt).

## 9. Canonical gate completeness
- **Repair:** `make check` → `scripts/run_all_gates.py`: dependency-lock,
  pip-check, full tests, prediction court, fixture, Python verifier, Node
  verifier, governance, benchmark court, sealed evolution, full-decision
  replay, non-vacuous battery fixture, mutation battery, power analysis,
  parameter shift, independent generator, semantic checks, DOM runtime
  contract, REAL browser, package verification — with a completeness guard:
  PASS is printed only if every required gate ran and exited 0.

## 10. Receipts reconciliation
- **Repair:** this receipts_v4/ set supersedes all prior receipts;
  `RECEIPT_STATUS_INDEX.md` marks every historical receipt
  SUPERSEDED_V1/V2/V3 (historical content preserved byte-identical under
  receipts_superseded/); all corrections/withdrawals enumerated in
  `V4_CLAIM_LEDGER.md` §A.

## Test adaptations (documented per the no-weakening rule)
- `tests/test_evolution.py`: stub body gained charge_row_hash/terminal_status
  and kind promotion_look_result (new signed-row shape). No assertion removed.
- `tests/test_replay_full_decision.py`: added `evaluator.finalize()` before
  reveal (the V4 lifecycle makes the old flow — reveal during EVALUATING —
  correctly impossible). Assertions unchanged.
- `tests/test_charged_access.py` truth-leak probe asserts the precise
  boundary (target truth keys/values) rather than a blunt substring that also
  matched legitimate historical prior-task outcomes (training inputs).
- All other 190+ tests unchanged.
