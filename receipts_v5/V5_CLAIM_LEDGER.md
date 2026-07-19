# V5 CLAIM LEDGER — Eagle Eye Zenith (canonical, supersedes V1–V4)

This is the ONE current claim ledger. All prior ledgers are historical under
`receipts_superseded/` (V1–V3) and `receipts_superseded/v4/` (V4) and are kept
byte-identical — supersession is expressed by location + this document, never
by editing a generated receipt after the fact.

Evidence classes (the only permitted vocabulary):
**MECHANICALLY VERIFIED** · **SYNTHETICALLY VERIFIED** · **THEOREM-CONDITIONAL** ·
**MODEL-CONDITIONAL ESTIMATE** · **EXTERNALLY VALIDATED** (currently NOTHING) ·
**NOT ESTABLISHED**.

## A. What is new/changed in V5 vs the verified V4 kernel

| Area | Change | Class | Evidence |
|---|---|---|---|
| Setup portability | `scripts/preflight.py` surfaces foreign PYTHONPATH/PYTHONHOME and package shadowing (non-mutating); `--strict` fails closed and is gate 0. Makefile pip/interpreter steps run under `env -u PYTHONPATH -u PYTHONHOME`; gate runner scrubs PYTHONHOME and pins PYTHONPATH=src | MECHANICALLY VERIFIED | `tests/test_preflight.py` (5); preflight gate in `make check` |
| Chain identity binding | `verify_chain` (Python + Node) binds the anchor's signed `chain_id`/`run_id` to every row and supports caller-side `expected_chain_id`/`run_id` pinning — closes cross-chain confusion under signer-key reuse | MECHANICALLY VERIFIED | `tests/test_signed_chain.py` (cross-chain-presentation, spliced-row); dual-runtime replay parity |
| Fail-closed verification | malformed signer PEM / signature returns `{verified:False}` instead of raising | MECHANICALLY VERIFIED | `tests/test_signed_chain.py::test_malformed_signer_pem_fails_closed` |
| Pilot seam | `src/eagle_eye/adapters.py` — Null adapters for live-data / KMS / identity / durable-audit / external-execution raise `AdapterDisabled`; `pilot_status()` reports every capability NOT ESTABLISHED; flipping a config flag without a real backend still fails closed | MECHANICALLY VERIFIED | `tests/test_adapters.py` (4) |
| Operator UX | readable node inspector (no raw JSON dump); wired Fit + 4 layer controls (were dead); action lifecycle strip (REQUESTED→PENDING_APPROVAL→APPROVED_SHADOW→EXTERNALLY_EXECUTED·OFF) with explanatory note; decomposed honest proof chips (no single misleading "READY"); hash wrapping; mobile overflow fixed | MECHANICALLY VERIFIED | `scripts/browser_verification.py` (20 checks incl. INSPECTOR_NO_RAW_JSON, FIT_CONTROL_LIVE, LAYER_TOGGLE_LIVE, ACTION_LIFECYCLE_STRIP, PROOF_STATE_DECOMPOSED, NO_MOBILE_HORIZONTAL_OVERFLOW) |

## B. Carried forward from V4 (unchanged mechanisms, re-verified in V5)

| Claim | Class | Evidence |
|---|---|---|
| CSPRNG evaluator secret; commitment binds secret+provenance; irreversible INITIALIZED→EVALUATING→FINALIZED→REVEALABLE; reveal hard-fails before FINALIZED | MECHANICALLY VERIFIED | `tests/test_evaluator_lifecycle.py` |
| Every holdout access charged BEFORE candidate code; success/exception/timeout/malformed all consume the look; fresh nonce cannot buy a free failed query; captured inputs contain no target truth | MECHANICALLY VERIFIED | `tests/test_charged_access.py` |
| Full-decision replay from the bundle alone; every binding-field mutation exits nonzero; vacuous runs labeled and never called full replay | MECHANICALLY VERIFIED | `scripts/replay_sealed_evolution.py`; `scripts/replay_mutation_battery.py` (19/19) |
| Dependency provenance mandatory (never NOT_AVAILABLE); running env matches audited lock; pip check clean | MECHANICALLY VERIFIED | `tests/test_provenance.py`; setup + gates |
| Suite scaling is stratum-preserving independent resampling; Type-I ≈0.000–0.005 vs allocated 0.0025; power ≈0.90/0.96 at −0.02 nats | MODEL-CONDITIONAL ESTIMATE | `scripts/power_analysis.py` |
| Signed chains reject rewrite/truncate/reorder/substitute/forge in Python AND Node | MECHANICALLY VERIFIED | `tests/test_signed_chain.py`; `verifier/verify_chain.mjs` |
| Package: internal root EAGLE_EYE_ZENITH_FABLE_HANDOFF_V5, all members manifested, no unsafe paths/symlinks, 113 PNGs | MECHANICALLY VERIFIED | `scripts/verify_package.py --zip` |

## C. Synthetic findings (per-run, receipt-bound — NOT invariants)

- Sealed promotion outcomes vary per CSPRNG run. `NO_CHALLENGER_EARNED_PROMOTION`
  is the common result; borderline promotions occur and are fully
  replay-verified either way. **The exact promotions/rejections/replay-decision
  counts belong to a specific run** — see the machine-readable
  `V5_GATE_RESULTS.json` and `state.json` of the bound run in the delivery
  folder. No prose in this repo presents any single run's count as universal.
- In-family parameter shift: NLL transfer ESTABLISHED; CRPS transfer NOT
  ESTABLISHED (SYNTHETICALLY VERIFIED).
- Structurally independent generator: champion advantage over baseline NOT
  ESTABLISHED (CI straddles zero); calibration stayed in band (the gated trust
  property held) (SYNTHETICALLY VERIFIED).

## D. NOT ESTABLISHED (see V5_HONEST_REMAINING_WALLS.md)

Organizational evaluator isolation · production KMS/identity · durable external
transparency storage · any live-data / operational claim · champion advantage
on alien generators · general self-improvement · universal transfer advantage ·
real external execution. **EXTERNALLY VALIDATED: nothing.** The V5 pilot
adapters are fail-closed seams, not infrastructure.

## E. Standing prohibitions honored

No gate lowered, no tolerance widened, no hard test deleted/weakened for green
(all test adaptations documented in V5_REPAIR_MAP.md). No generated receipt
hand-edited after generation. `external_action`/external execution false
throughout. The canonical repository was reconstructed at 46f6e2f on an
isolated branch; nothing merged or pushed — the graft is human-gated
(INTEGRATION_INSTRUCTIONS.md).
