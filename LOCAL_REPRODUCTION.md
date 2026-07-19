# EAGLE EYE ZENITH — V8 LOCAL REPRODUCTION

Candidate source for local verification. **Do not merge into
`/Users/Apple/Projects/eagle-eye-zenith` until your own verification passes.**
Everything here is fixture/synthetic; `external_action=false` throughout. V8
adds the replayable **W-transfer** court on top of the verified V7 tree.

## 0. Requirements
- Python 3.11 (3.11.15 was the build interpreter), Node ≥ 20, GNU make
- Network on first `make setup` (pip pins + Playwright Chromium shell)
- No Docker / PostgreSQL required: the pilot ships a SQLite + filesystem
  reference backend behind the same interfaces (see PILOT_OPERATOR_RUNBOOK).

## 1. Setup (exact audited dependency set + launcher preflight)
```bash
make setup
# venv from environment/requirements-lock.txt (exact pins), pip check,
# lock-vs-environment verification, Playwright Chromium shell install.
# If a launcher exports a foreign PYTHONPATH/PYTHONHOME (e.g. Hermes), the
# Makefile scrubs it for pip/interpreter steps; preflight surfaces it loudly.
```

## 2. The canonical gate (V8 — everything, or no PASS)
```bash
make check
# scripts/run_all_gates.py runs ALL 33 required gates, including:
# preflight, dependency-lock, pip-check, tests (423), prediction-court,
# fixture, verify-python, verify-node, governance, benchmark-court,
# sealed-evolution, full-decision-replay, deterministic W-transfer baseline,
# w-transfer, w-transfer-replay,
# strangers-verifier (V9: standalone stdlib-only verifier court, python3 -I),
# live-shadow-rehearsal (V10: full live path on a test-fixture authority),
# custody-rehearsal (V11: KMS/OIDC state ladder + round-trip interlock),
# execution-rehearsal (V12: licensed execution — armed, licensed, reversible),
# recursive-evolution (V7),
# battery-fixture, mutation-battery,
# power-analysis, parameter-shift, independent-generator, semantic-check,
# dom-contract, browser (REAL Chromium),
# pilot-smoke, failure-court, pilot-browser, pilot-performance (V6),
# package-verify.
# Writes artifacts/check/V8_GATE_RESULTS.json (per-gate command + exit code).
# Prints EAGLE_EYE_ZENITH_CHECK_PASS only if every gate ran and exited 0.
```
Expect ~15–25 minutes. The sealed benchmark uses a FRESH CSPRNG evaluator
secret per run — receipt ids differ run-to-run by design; reproducibility is
via the revealed bundle, not secret re-derivation.

## 3. Individual gates (inherited)
```bash
make test                  # 395 tests
make strangers-verifier    # V9: standalone verifier accepts real bundles,
                           # refuses the doctored battery (zero repo trust)
make live-shadow-rehearsal # V10: full live-tenant path on a fixture authority;
                           # READY while LIVE stays unreachable (see runbook)
make sealed-evolution      # benchmark (CSPRNG secret, suite scale 3)
make replay                # full-decision replay of the latest bundle
make recursive-evolution   # V7: 3 sealed rounds, each independently replayed,
                           # admitted to the anytime-valid e-process ledger,
                           # feedback state evolved between rounds
make mutation-battery      # 19 binding-field mutations must all fail replay
make power-analysis        # measured Type-I + power of the exact rule
make parameter-shift       # in-family shift (honest label)
make independent-generator # structurally independent family, 100 seeds
make dom-contract          # Node runtime contract (real JS, DOM shim)
make browser               # REAL headless Chromium workflow (V5 cockpit)
make package-verify        # tree vs manifest (from a clean extraction)
```

## 4. The V6 pilot (operator command surface)
```bash
make pilot-setup           # init home, migrations from empty, evaluator token
make pilot-up              # start evaluator + cockpit processes (health-wait)
make pilot-check           # health + readiness + migration status
make pilot-smoke           # full loop over real HTTP (22 steps)
make pilot-backup          # consistent backup + hash manifest
make pilot-restore-check   # restore into scratch, reproduce audit heads
make pilot-down            # graceful shutdown + cleanup
# then open http://127.0.0.1:8765/pilot.html  (operator cockpit)
# V6 verification gates:
make pilot-failure-court   # 39 executed negative/injection cases
make pilot-browser         # REAL Chromium operator-loop checks (desktop+mobile)
make pilot-performance     # labeled local synthetic workload measurements
```

## 5. Cockpit
```bash
make run                   # http://127.0.0.1:8765  (EAGLE_EYE_PORT to change)
# /            → V5 verified-run command view
# /pilot.html  → V6 pilot operator cockpit (full ingest→…→export loop)
```

## 6. What to read (canonical current set = receipts_v8/ + inherited receipts)
- `receipts_v8/V8_W_TRANSFER_DESIGN.md` — preregistered family panel,
  seed-cluster e-processes, deterministic fixture baseline, and replay rules
- `receipts_v8/V8_CLAIM_LEDGER.md` — V8 delta claims with evidence classes
- `receipts_v8/V8_HONEST_REMAINING_WALLS.md` — CURRENT walls
- `receipts_v8/V8_REPAIR_MAP.md` — mission item → change → enforcing test/gate
- `receipts_v7/V7_RECURSIVE_EVOLUTION_DESIGN.md` — the V7 loop: e-process
  ledger math + validity, feedback harness, what a crossing does/doesn't mean
- `receipts_v7/V7_CLAIM_LEDGER.md` — V7 delta claims with evidence classes
- `receipts_v7/V7_HONEST_REMAINING_WALLS.md` — CURRENT walls (supersedes V6's)
- `receipts_v7/V7_REPAIR_MAP.md` — mission item → change → enforcing test/gate
- `receipts_v6/V6_CLAIM_LEDGER.md` — every claim with its evidence class
- `receipts_v6/V6_HONEST_REMAINING_WALLS.md` — what is still NOT established
- `receipts_v6/V6_REPAIR_MAP.md` — mission item → change → enforcing test/gate
- `receipts_v6/PILOT_OPERATOR_RUNBOOK.md` — deploy, operate, back up, recover
- `receipts_v6/FAILURE_RECOVERY_RUNBOOK.md` — failure modes → recovery steps
- `receipts_v5/` — the merged V5 receipt set (carried, still valid)
- `receipts_superseded/` — V1–V4 historical receipts
- `docs/V4_REPLAY_SCHEMA.json` — binding vs informational bundle fields

## 7. Expected honest outcomes (do not "fix" these)
- Sealed promotion outcomes VARY PER RUN (fresh CSPRNG suite each run):
  `NO_CHALLENGER_EARNED_PROMOTION` is the common result; the main-run replay
  is often `VACUOUS_INTEGRITY_ONLY` (0 sealed decisions) and is labeled as
  such — it is NEVER presented as a full-decision replay. The pinned battery
  fixture is the invariant non-vacuous proof (19/19 mutations detected).
- Independent-generator advantage NOT ESTABLISHED (CI straddles zero;
  calibration stays in band — the gated trust property).
- In-family transfer: NLL ESTABLISHED, CRPS NOT ESTABLISHED.
- Pilot production capabilities (live data, KMS, OIDC, durable external audit,
  external execution) are all NOT ESTABLISHED fail-closed seams — see
  receipts_v6/V6_HONEST_REMAINING_WALLS.md.
