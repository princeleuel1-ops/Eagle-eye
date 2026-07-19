PYTHON ?= python3.11
VENVPY = .venv/bin/python
# V5 setup portability: SCRUB inherited PYTHONPATH/PYTHONHOME for pip and
# interpreter steps so a launcher (e.g. Hermes exporting
# PYTHONPATH=/Users/Apple/.hermes/hermes-agent) cannot contaminate pip's
# distribution discovery or shadow the project package. Project code that
# genuinely needs the source root sets PYTHONPATH=src explicitly per-recipe,
# which overrides the scrub for exactly that call. We never mutate the
# operator's shell — only the subprocess environment of these recipes.
CLEAN = env -u PYTHONPATH -u PYTHONHOME

.PHONY: preflight setup lock test fixture verify verify-node governance benchmark prediction-court \
        sealed-evolution replay w-transfer-baseline w-transfer w-transfer-replay strangers-verifier live-shadow-rehearsal custody-rehearsal execution-rehearsal recursive-evolution mutation-battery power-analysis parameter-shift \
        independent-generator semantic-check dom-contract browser package-verify \
        package check run clean evolve-loop \
        pilot-setup pilot-up pilot-down pilot-check pilot-smoke pilot-backup \
        pilot-restore-check pilot-browser pilot-failure-court pilot-performance pilot-tests

# Loud, non-mutating diagnostic for launcher contamination.
preflight:
	$(CLEAN) $(PYTHON) scripts/preflight.py

# V4 blocker 4 + V5 portability: setup installs the EXACT audited dependency
# set from the lock under a scrubbed environment, verifies it, passes pip check.
setup:
	$(PYTHON) scripts/preflight.py || true
	$(CLEAN) $(PYTHON) -m venv .venv
	$(CLEAN) $(VENVPY) -m pip install --upgrade pip
	$(CLEAN) $(VENVPY) -m pip install -r environment/requirements-lock.txt
	$(CLEAN) $(VENVPY) -m pip install -e . --no-deps
	$(CLEAN) $(VENVPY) -m pip check
	$(CLEAN) env PYTHONPATH=src $(VENVPY) -c "from pathlib import Path; from eagle_eye.provenance import verify_dependency_lock; r = verify_dependency_lock(Path('.')); assert r['all_match'], r; print('DEPENDENCY_LOCK_VERIFIED', r['lock_sha256'])"
	$(CLEAN) $(VENVPY) -m playwright install chromium --only-shell

lock:
	$(VENVPY) -m pip freeze --all | grep -v "^pip==" | grep -v "^setuptools==" | sort > environment/requirements-lock.txt

test:
	PYTHONPATH=src $(VENVPY) -m pytest

fixture:
	PYTHONPATH=src $(VENVPY) scripts/run_fixture.py

verify:
	PYTHONPATH=src $(VENVPY) scripts/verify_evidence_room.py artifacts/runs/latest/evidence-room.zip artifacts/runs/latest/trust-registry.json tenant-demo

verify-node:
	node verifier/verify.mjs artifacts/runs/latest/evidence-room.zip --trust-registry artifacts/runs/latest/trust-registry.json --expected-tenant tenant-demo

governance:
	PYTHONPATH=src $(VENVPY) scripts/run_governance_fixture.py

benchmark:
	PYTHONPATH=src $(VENVPY) scripts/run_benchmark_court.py

prediction-court:
	PYTHONPATH=src $(VENVPY) scripts/run_prediction_court.py

sealed-evolution:
	PYTHONPATH=src $(VENVPY) scripts/run_sealed_evolution.py

replay:
	PYTHONPATH=src $(VENVPY) scripts/replay_sealed_evolution.py artifacts/evolution/latest/REPLAY_BUNDLE.json

w-transfer-baseline:
	PYTHONPATH=src $(VENVPY) scripts/run_w_transfer_baseline.py

w-transfer: w-transfer-baseline
	PYTHONPATH=src $(VENVPY) scripts/run_w_transfer.py --champion-bundle artifacts/transfer/baseline/REPLAY_BUNDLE.json

w-transfer-replay:
	PYTHONPATH=src $(VENVPY) scripts/replay_w_transfer.py artifacts/transfer/latest/W_TRANSFER_BUNDLE.json artifacts/transfer/latest/W_TRANSFER_RECEIPT.json

# V9: the stranger's verifier court — the standalone stdlib-only verifier
# (verifier_standalone/) must accept every real bundle and refuse every
# doctored one, running under `python3 -I` with zero repository trust.
strangers-verifier:
	PYTHONPATH=src $(VENVPY) scripts/run_strangers_court.py

# V10: live-shadow spine dress rehearsal — the full live-tenant path exercised
# on a TEST-FIXTURE authority; proves READY while LIVE stays unreachable
# without a signed production data-authority config (see LIVE_ACTIVATION_RUNBOOK).
live-shadow-rehearsal:
	PYTHONPATH=src $(VENVPY) scripts/run_live_shadow_rehearsal.py

# V11: custody & identity rehearsal — state ladder + remote round-trip protocol
# proven on labeled local providers; production VERIFIED unreachable here.
custody-rehearsal:
	PYTHONPATH=src $(VENVPY) scripts/run_custody_rehearsal.py

# V12: licensed-execution rehearsal — arming, per-action licenses, proof-chain
# receipts, reversal; production execution unreachable without the ceremony.
execution-rehearsal:
	PYTHONPATH=src $(VENVPY) scripts/run_execution_rehearsal.py

# V7: recursive self-verifying evolution — sealed rounds through the feedback
# harness, independent replay of EVERY round, anytime-valid e-process ledger.
recursive-evolution:
	PYTHONPATH=src $(VENVPY) scripts/run_recursive_evolution.py --rounds 3

mutation-battery:
	PYTHONPATH=src $(VENVPY) scripts/replay_mutation_battery.py

power-analysis:
	PYTHONPATH=src $(VENVPY) scripts/power_analysis.py

parameter-shift:
	PYTHONPATH=src $(VENVPY) scripts/run_parameter_shift_eval.py

independent-generator:
	PYTHONPATH=src $(VENVPY) scripts/run_independent_generator_eval.py

semantic-check:
	PYTHONPATH=src $(VENVPY) scripts/semantic_check.py

dom-contract:
	node verifier/dom_contract_test.mjs

browser:
	PYTHONPATH=src $(VENVPY) scripts/browser_verification.py

package-verify:
	PYTHONPATH=src $(VENVPY) scripts/verify_package.py --tree

package:
	$(CLEAN) $(VENVPY) scripts/build_package.py EAGLE_EYE_ZENITH_FABLE_HANDOFF_V8.zip

# ---------------------------------------------------------------------------
# V6 PILOT FORGE — one coherent operator command surface (local reference).
# Everything is FIXTURE-tenant, labeled dev issuer, external execution
# fail-closed. Local Postgres/object-store are NOT shipped here; the SQLite +
# filesystem reference backends satisfy the same interfaces.
# ---------------------------------------------------------------------------
pilot-setup:
	PYTHONPATH=src $(VENVPY) -m eagle_eye.pilot.ops setup

pilot-up:
	PYTHONPATH=src $(VENVPY) -m eagle_eye.pilot.ops up

pilot-down:
	PYTHONPATH=src $(VENVPY) -m eagle_eye.pilot.ops down

pilot-check:
	PYTHONPATH=src $(VENVPY) -m eagle_eye.pilot.ops check

pilot-backup:
	PYTHONPATH=src $(VENVPY) -m eagle_eye.pilot.ops backup

pilot-restore-check:
	PYTHONPATH=src $(VENVPY) -m eagle_eye.pilot.ops restore-check

pilot-tests:
	PYTHONPATH=src $(VENVPY) -m pytest -q tests/test_pilot_storage.py tests/test_pilot_identity_kms.py tests/test_pilot_objectstore_observability.py tests/test_pilot_ingest.py tests/test_pilot_shadow.py tests/test_evaluator_isolation.py

pilot-smoke:
	PYTHONPATH=src $(VENVPY) scripts/pilot_smoke.py

pilot-failure-court:
	PYTHONPATH=src $(VENVPY) scripts/failure_court.py

pilot-browser:
	PYTHONPATH=src $(VENVPY) scripts/pilot_browser_verification.py

pilot-performance:
	PYTHONPATH=src $(VENVPY) scripts/pilot_performance.py

# V4 blocker 9 + V5 portability: the canonical gate runs preflight (loud,
# non-fatal) then delegates to scripts/run_all_gates.py under a scrubbed
# environment. The runner runs EVERY required gate and refuses to print PASS
# if any headline mechanism was skipped or failed (completeness guard inside).
check:
	$(CLEAN) env PYTHONPATH=src $(VENVPY) scripts/run_all_gates.py

run:
	PYTHONPATH=src $(VENVPY) -m eagle_eye.server

clean:
	rm -rf artifacts/runs/latest artifacts/check artifacts/browser artifacts/evolution/battery-fixture .pytest_cache

evolve-loop:
	PYTHONPATH=src $(VENVPY) scripts/run_forever.py 0
