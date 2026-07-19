# V4 ADVERSARIAL TEST RESULTS

All probes below are MECHANICALLY VERIFIED: each is an executable test or
script in this archive; commands cited. Counts refer to the packaged test
suite (214 tests, 31 files). Reproduce with `make check` from a clean
extraction.

## 1. Early-reveal probe (audit blocker 1 — REQUIRED negative test)
`tests/test_evaluator_lifecycle.py`
- Reveal in INITIALIZED → **hard failure** (`reveal refused before FINALIZED`). ✓
- Reveal in EVALUATING (after a real spent look) → **hard failure**. ✓
- After `finalize()` → reveal succeeds; lifecycle REVEALABLE; irreversible
  (second finalize refused; compare/final_audit refused post-finalize). ✓
- Early suite reconstruction: private attrs unreachable (name-mangled, tested);
  the only pre-reveal publics are one-way hashes (commitment + suite content
  hashes). The V3 derived-secret pattern (`evaluator-secret-{seed}-{rev}`)
  is greppably absent and the CSPRNG boundary is the default path. ✓

## 2. Failed-request / charge-before-execution probes (audit blocker 2)
`tests/test_charged_access.py`
- **REQUIRED probe:** candidate captures its input and raises 3× with 3 fresh
  nonces → `LOOKS_SPENT=3`, `LEDGER: 3 charge rows + 3 result rows`, all
  results terminally **FAILED**; alpha burned = 3 × per-look. No free holdout
  observations. ✓
- Captured contexts contain NO target truth: no outcomes/theta/hyper/
  p_stockout/regime_id structure, and the rebuilt suite's actual
  `log_final_delay` truth values do not appear in the captured bytes.
  (Historical prior-task outcomes ARE present — they are training inputs by
  design, not holdout truth.) ✓
- Charge row lands BEFORE candidate code first executes (probe reads the
  ledger from inside the candidate). ✓
- Timeout probe (SIGALRM budget): sleeping candidate → charged look,
  terminal **TIMED_OUT**. ✓
- Two failed looks at max_looks=2 → budget exhausted; third refused pre-charge. ✓
- Replayed nonce → refused pre-charge AND pre-execution (no free query). ✓
- Malformed response (missing 'interventions') → raises, charged, **FAILED**
  (no longer masquerades as abstention). ✓
- Failed final audit consumes the strict one-shot. ✓

## 3. Full-decision replay + mutation battery (audit blocker 3)
- Canonical replay: 33 checks PASS, `DECISIONS_RECOMPUTED>0 MISMATCHED=0`,
  `REPLAY_RESULT=PASS_FULL_DECISION` (see V4_GATE_RESULTS.json for the run
  bound to this archive).
- Mutation battery (`scripts/replay_mutation_battery.py`): **19/19 mutations
  detected** (exit nonzero each), covering: final_registry_manifest_sha256,
  controller_run_seed, cycle_cutoffs, live_world, policy_registry,
  resolutions, candidate ID, snapshot ID, registry binding, alpha fields,
  aggregate metrics, final-audit values, lineage state+reasons, evaluator
  secret, suite scale, genesis config, committed prediction blocks, grown
  tasks, base registry manifest. In-chain mutations are caught first by
  Ed25519 signature verification (catch-point recorded per mutant in
  MUTATION_BATTERY_RESULTS.json).
- Non-vacuous CLI fixture: precommitted secret `fx2` at seed 550 provably
  spends a sealed look; `tests/test_replay_cli_end_to_end.py` runs the actual
  CLI end-to-end and a fast mutation subset.
- Vacuous honesty: zero-look bundles print
  `REPLAY_RESULT=VACUOUS_INTEGRITY_ONLY` and are never called full replay.

## 4. Signed-chain attack battery (carried from V2, still green)
`tests/test_signed_chain.py`: rewrite-and-rehash (attacker relinks but cannot
re-sign), tail truncation vs anchor, reorder, signer substitution, forged
anchor signature, wrong tenant — all rejected, in Python and Node.

## 5. Cockpit adversarial states (audit blocker 8)
`verifier/dom_contract_test.mjs`: the exact V3 crash input (last_rejection
without lineage_hash; null last_promotion; missing voi_latest) renders safe
fallbacks with zero JS errors. Real-browser workflow
(`scripts/browser_verification.py`): zero console errors, zero failed
requests, no unavailable panels, screenshot receipt.

## 6. Honest findings preserved (not "fixed" away, not inflated)
- Promotion outcomes are PER-RUN under CSPRNG suites: most observed runs end
  NO_CHALLENGER_EARNED_PROMOTION; run `sevo4-51a4e71deb16` recorded one
  borderline, replay-verified promotion (CI upper −0.00025 nats). Both
  directions are reported with their receipts; neither is forced.
- Independent-generator advantage NOT ESTABLISHED (CI straddles zero).
- In-family CRPS transfer NOT ESTABLISHED.
These are findings the machinery is designed to surface; forcing them in
either direction would violate the standing prohibitions.
