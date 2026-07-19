# Architecture and Implementation Map — Post-Zenith Eagle Eye

## Pipeline (mission-conform)
```
regimes.py            synthetic worlds: regime λ → task θ_i → observations (hidden truth separated)
prior_registry.py     data contract: as-of windows, tenancy, provenance, deterministic releases + tamper detection
prior_selector.py     boundary filter → similarity ranking → inclusion/exclusion receipt (int-only, hash-recomputable)
                      compile_prior_context(): <prior> D1..DK <target> obs+query, manifest committed
predictors.py         one interface, seven implementations:
                        climatology · no_prefix (baseline) · naive_pooling (anti-pattern)
                        seq_prefix (order-sensitive EB analog) · set_mt (permutation-invariant EB analog)
                        oracle_hier (exact hierarchical Bayes, true variance components) · oracle_true (upper bound)
governor.py           support_state / shift_score / K+context validation → widen or abstain (fail closed)
prediction_court.py   sealed dev+holdout suites (distinct seeds), attack battery, proper-scoring metrics,
                      AND-chain promotion, deterministic receipt (latency measured but excluded from id)
posterior_engine.py   registry→selector→compiler→governed candidate→intervention comparison→commitments
                      (refuses any candidate without a court promotion; refuses registry mismatch)
evidence.py           posterior commitments inside the SIGNED manifest; fail-closed recomputation
verifier/verify.mjs   full Node parity incl. quantize-micro commitment recompute
web/posterior.js      cockpit panel; recomputes the distribution commitment in-browser (WebCrypto)
```

## Files changed/added vs commit 46f6e2f
NEW src: stats.py, regimes.py, prior_registry.py, prior_selector.py, predictors.py, governor.py, prediction_court.py, posterior_engine.py
NEW tests: test_stats.py, test_prior_registry.py, test_predictors.py, test_prediction_court.py, test_posterior_engine.py, test_posterior_evidence.py
NEW scripts: run_prediction_court.py · NEW web: posterior.js
MODIFIED: evidence.py (posterior export+verify), verifier/verify.mjs (parity), semantics.py (+9 checks),
scripts/run_fixture.py (engine attach + status lines), scripts/verify_evidence_room.py (+POSTERIOR_VERIFIED),
web/index.html (+posterior section), web/styles.css (+panel styles), Makefile (+prediction-court in check),
tests/test_semantics.py (+posterior contract test)
UNTOUCHED: kernel, audit, identity, policy, governance, ingestion, signing, server, benchmark, evaluator (trust stack extended, never weakened)

## Canonicalization contract
- canonical bytes: json.dumps(sort_keys=True, separators=(",",":")) ≡ Node canonicalize+JSON.stringify
- recomputed-hash surfaces are float-free (milli/micro ints) or quantize-micro'd (int-valued floats→int; else floor(x·1e6+0.5)) — identical in Python/Node/browser
- stable ids: prefix-sha256(canonical)[:12]

## Evidence chain additions (inside signed manifest + run.json)
predictive_distribution_commitment · intervention_set_commitment · prior_manifest_sha256 ·
prior_registry_manifest_sha256 · calibration_receipt_sha256 · court_receipt_id · K · context_length ·
support_state · shift_score_micro · abstained · model_release (+ model_artifact_sha256, training_support,
feature_schema_release, generator_release, selection receipt, excluded-task reasons in run.json)
