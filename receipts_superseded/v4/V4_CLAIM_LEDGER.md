# V4 CLAIM LEDGER — Eagle Eye Zenith (supersedes all prior claim ledgers)

Evidence classes used (and the ONLY vocabulary permitted for claims):
**MECHANICALLY VERIFIED** (a machine checked it in this repo; command cited) ·
**SYNTHETICALLY VERIFIED** (measured against authorized synthetic truth) ·
**THEOREM-CONDITIONAL** (holds under stated assumptions) ·
**MODEL_CONDITIONAL_ESTIMATE** (measured under a stated model/bootstrap) ·
**EXTERNALLY VALIDATED** (verified outside this environment — currently NOTHING) ·
**NOT ESTABLISHED** (do not rely on it).

## A. Corrections and withdrawals required by the V3 audit (blocker 10)

| Prior claim | Status | V4 correction |
|---|---|---|
| Test counts "128", "167", "184" (V1–V3 receipts) | SUPERSEDED | V4 exact count: **214 tests, 31 files** (`python -m pytest --collect-only -q`); every historical count applies only to its superseded receipt set |
| "One promotion + one rejection proven" (V1) | WITHDRAWN (since V2) | The V1 promotion predated the real precommitted statistical rule and stays withdrawn. Under the real rule, outcomes are per-run findings bound to receipts (see §C); rejections are proven in the signed lineage of every run |
| "113 PNG assets included" for archives that omitted them (V2/V3 zips listed them in manifests while excluding the files) | CORRECTED | The V4 archive **contains** all 113 PNGs; `scripts/verify_package.py --zip` fails on any missing/unmanifested member and enforces the count |
| "Full decision replay RESOLVED" (V3 W10) | WITHDRAWN | V3 recomputed selected paired-statistic fields only. V4 implements actual full-decision replay: suites, registries, grown tasks, predictions, resolutions, propensities, candidates, snapshots, dev pre-screens, aggregates, statistics, alpha accounting, gate states/reasons, final audit, and 1:1 chain mappings — MECHANICALLY VERIFIED (`scripts/replay_sealed_evolution.py`, 33 checks; 19/19 mutation battery) |
| "Cross-generator evaluation RESOLVED — prior transfer survives a generator swap" (V3 W10) | WITHDRAWN | That test was an **in-family parameter shift** evaluated with `default_config()` and gated on NLL alone. V4 relabels it (`run_parameter_shift_eval.py`) and adds a structurally independent generator (`run_independent_generator_eval.py`). Findings below. |
| "Statistical power tripled" (V3 W10) | WITHDRAWN | V3 "scaling" incremented `n_target_obs`, changing stratum composition. V4 scaling is stratum-preserving independent resampling; power is now **measured** (see D) |
| V3 evaluator secret `evaluator-secret-{live_seed}-{code_revision}` treated as sealed | DEFECT CONFIRMED, REPAIRED | The secret was derivable from public metadata → suites reconstructable pre-run. V4: CSPRNG operator boundary + irreversible lifecycle; regression test greps the old pattern out of existence |
| Internal archive root named `..._V2` in the V3 zip | DEFECT CONFIRMED, REPAIRED | V4 archive root is exactly `EAGLE_EYE_ZENITH_FABLE_HANDOFF_V4` (enforced by `verify_package.py --zip`) |

## B. What V4 mechanically verifies (commands cited)

| Claim | Class | Evidence |
|---|---|---|
| Evaluator secret is CSPRNG-provisioned; commitment binds secret+provenance; reveal HARD-FAILS before FINALIZED; no looks after finalize; lifecycle irreversible | MECHANICALLY VERIFIED | `tests/test_evaluator_lifecycle.py` (7 tests); lifecycle FINALIZED row in the signed evaluator chain; replay checks `LIFECYCLE_*` |
| Every holdout access is charged BEFORE candidate code executes; success/exception/timeout/malformed all end in terminal-status rows; fresh nonces cannot buy free failed queries; failed looks burn alpha; captured candidate inputs contain no target truth | MECHANICALLY VERIFIED | `tests/test_charged_access.py` (7 adversarial tests; the required 3-nonce capture probe shows LOOKS_SPENT=3, 3 charge rows, 3 FAILED results) |
| Full-decision replay from the bundle alone; every binding field mutation exits nonzero | MECHANICALLY VERIFIED | `scripts/replay_sealed_evolution.py` (33 checks, dual-runtime chain verification); `scripts/replay_mutation_battery.py` (19/19 detected); non-vacuous CLI fixture in `tests/test_replay_cli_end_to_end.py` |
| Vacuous replays are labeled VACUOUS_INTEGRITY_ONLY and never called full-decision replay | MECHANICALLY VERIFIED | replay CLI output contract + battery receipt |
| One evaluator version constant everywhere (no 2.0/2.1 mismatch) | MECHANICALLY VERIFIED | `tests/test_evaluator_lifecycle.py::test_single_evaluator_version_constant` |
| `dependency_lock_sha256` always present, never NOT_AVAILABLE; running env matches the audited pins; pip check clean | MECHANICALLY VERIFIED | `tests/test_provenance.py`; `make setup`; `dependency-lock` + `pip-check` gates |
| Suite scaling preserves the exact stratum/observation-count distribution with independent case resampling | MECHANICALLY VERIFIED | `tests/test_suite_scale.py` |
| Cockpit renders with zero JS errors, zero failed requests, no unavailable panels; V3 crash (missing `last_rejection.lineage_hash`) fixed with versioned contract + fallbacks | MECHANICALLY VERIFIED | real Chromium workflow `scripts/browser_verification.py` (15 checks) + `verifier/dom_contract_test.mjs` (12 checks incl. degraded-state regression) |
| Archive completeness: internal root V4, all members manifested, no unmanifested payloads, no symlinks/unsafe paths, 113 PNGs present | MECHANICALLY VERIFIED | `scripts/verify_package.py --zip` |
| `make check` cannot print PASS with any headline mechanism skipped | MECHANICALLY VERIFIED | completeness guard in `scripts/run_all_gates.py` (required-gate set diffed against ran set) |
| Signed chains: Ed25519 rows + external anchors; rewrite/truncate/reorder/substitute/forge all rejected in Python AND Node | MECHANICALLY VERIFIED | `tests/test_signed_chain.py`; `verifier/verify_chain.mjs` |

## C. What V4 measures on synthetic truth (honest findings, not forced)

| Finding | Class | Value |
|---|---|---|
| Sealed promotion outcomes (CSPRNG secret per run → outcomes are PER-RUN, receipt-bound findings) | SYNTHETICALLY VERIFIED | Observed runs at seed 550, scale 3: receipt `sevo4-d7bf0609bc10` — 0 promotions, 18 rejections, 3 SUCCEEDED looks; receipt `sevo4-51a4e71deb16` — **1 promotion** (`governor.shift_suspect_milli` 800→900; n=132, mean −0.0171 nats, one-sided 99.75% CI [−0.0340, −0.00025] — borderline), 17 rejections, 1 look, replay-verified bit-for-bit incl. the champion switch. Within-run FWER is Bonferroni-controlled; cross-run alpha is NOT pooled (see walls) |
| In-family parameter shift (original registry, shifted targets, signed champion config, 12 precommitted seeds) | SYNTHETICALLY VERIFIED | NLL transfer **ESTABLISHED** (CI95 [-0.202, -0.073]); CRPS transfer **NOT ESTABLISHED** (CI95 [-0.004, +0.031]); coverage in band (0.826) |
| Structurally independent generator (100 precommitted seeds, alien registry+targets) | SYNTHETICALLY VERIFIED | Champion advantage over no-prefix baseline **NOT ESTABLISHED**: NLL CI95 [-0.024, +0.042], per-seed failure rate 0.49; calibration did NOT break (coverage 0.888, in band) — trust holds, advantage does not |
| Type-I error of the exact promotion rule (planted delta = 0) | MODEL_CONDITIONAL_ESTIMATE | measured 0.000–0.005 vs allocated per-look alpha 0.0025 (iid + replica-block bootstrap, B=1200) |
| Power of the exact promotion rule | MODEL_CONDITIONAL_ESTIMATE | ~0.90 (scale 1, n≈44) and ~0.96 (scale 3, n≈132) at planted −0.02 nats; 1.00 at −0.05 nats — the rule is adequately powered for meaningful effects; observed whitelist effects are simply near zero |

## D. What remains NOT ESTABLISHED (see V4_HONEST_REMAINING_WALLS.md)

- Organizational evaluator isolation (in-process software boundary only)
- Production key custody (ephemeral in-run Ed25519 demo keys; no KMS)
- Sensitivity to unobserved confounding (no model implemented)
- Any live-data / operational claim (all evidence is synthetic)
- Champion advantage under structurally alien data-generating processes
- "Self-improving" as a GENERAL capability. The cockpit label activates per run when that run's lineage contains a verified promotion AND rejection (first occurrence: run `sevo4-51a4e71deb16`, a single borderline whitelist-parameter promotion). One receipted parameter change is NOT a general self-improvement claim
- EXTERNALLY VALIDATED: nothing — no claim in this repo has been verified outside this environment

## E. Standing prohibitions honored

No gate lowered, no tolerance widened, no test deleted or weakened to force
green (all test adaptations to the V4 API are documented in V4_REPAIR_MAP.md);
no receipt hand-edited after generation; `external_action=false` everywhere;
the canonical repository was not touched (it is not reachable from this
environment by construction).
