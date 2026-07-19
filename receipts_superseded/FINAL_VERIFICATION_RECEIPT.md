# Final Verification Receipt — Eagle Eye Bayesian Disruption Intelligence Engine

Run: zenith-2026-07-12-cmrio3uqv · Environment: Amazon Linux 2023, Python 3.11.15, Node v24.14.1
Base package: Drive folder 1NFbu7wNrWdZOaP3x44q85OSkRVkMn4xn, all 10 SHA-256 manifest hashes VERIFIED.
Canonical base state reproduced: commit 46f6e2f, 54/54 baseline tests passed before any change.

## Claim ledger

| # | Claim | Status | Evidence |
|---|---|---|---|
| 1 | Package reconstructed; 113 PNGs + 116 registry identities | VERIFIED | sha256 manifest match; inventory counts |
| 2 | Baseline gate chain green pre-change (54 tests, both verifiers, court, semantic) | VERIFIED | executed; exit codes 0 |
| 3 | Full suite green post-change: **128 passed** (54 baseline + 74 new) | VERIFIED | pytest 128 passed in 27.6s |
| 4 | Full gate chain green post-change (court→fixture→py verify→node verify→governance→benchmark→semantic) | VERIFIED | all exit 0; POSTERIOR_VERIFIED=true both runtimes |
| 5 | Prior task registry with as-of + tenancy + provenance enforcement, deterministic releases, tamper detection | VERIFIED | prior_registry.py + 14 tests incl. RED leakage tests |
| 6 | Selector + compiler preserve prior/target separation; deterministic inclusion/exclusion receipts; refuse leaky/foreign tasks | VERIFIED | prior_selector.py tests; CompilerError paths executed |
| 7 | Synthetic regime generator with hidden ground truth, shifts, heavy tails, missingness | VERIFIED | regimes.py; truth separation tested |
| 8 | Exact hierarchical Bayes oracle + 5 candidates + governed wrapper behind one interface | VERIFIED | predictors.py/governor.py, 13 tests |
| 9 | set_mt beats no-prefix on sealed holdout: NLL 0.777 vs 1.059, CRPS 0.333 vs 0.358, KL-to-oracle 0.380 vs 2.785, intervention regret 0.55d vs 4.38d | MEASURED | prediction-court receipt pcourt-* |
| 10 | Prior value greatest at scarce target evidence (paper's low-data claim) | MEASURED | scarcity subset: set_mt NLL ≪ no_prefix (see BENCHMARK_RESULTS.json nll_scarcity) |
| 11 | Sequential candidate order-sensitive (spread ~0.16–0.37 log-units); set candidate permutation-invariant (0.0) | MEASURED | permutation battery in court |
| 12 | Naive pooling drowns target evidence (mechanism) and scores worse | MEASURED | test_naive_pooling_drowns_target_evidence + court metrics |
| 13 | Negative transfer under wrong-class priors quantified (~0.56 nats NLL penalty) | MEASURED | unrelated_priors subset |
| 14 | Governor abstains outside validated K/context and on zero support; widens under weak support/shift | VERIFIED | governor tests + court probes 2/2 abstained |
| 15 | Court promoted governed_set_mt AND rejected dev-attractive overfit candidate (dev NLL 0.687 < baseline 0.872) | VERIFIED | RECURSIVE_PROMOTION_REJECTION_RECEIPT.json; proofs both true |
| 16 | Dev/holdout sealed with distinct world seeds; contamination detector fires on seed reuse | VERIFIED | contamination_check + test |
| 17 | Evidence room binds posterior commitments (distribution, prior manifest, calibration, court, K, context, support, shift) into the signed manifest | VERIFIED | evidence.py + fixture output |
| 18 | Python/Node/browser share one commitment discipline (quantize-micro); five tamper classes caught by BOTH runtimes under a re-signing attacker | VERIFIED | test_posterior_evidence.py 10/10 |
| 19 | Legacy rooms (no posterior block) verify unchanged; manifest-without-block forgery caught | VERIFIED | backward-compat + absence tests |
| 20 | Cockpit posterior panel: interval bands, probability chips, support/shift, provenance, calibration, abstention, falsification note, in-browser commitment recompute | VERIFIED (semantic + data-contract), IMPLEMENTED_NOT_EXECUTED (visual) | semantics checks 23/23; W3 |
| 21 | Demo run PO-17: median 12.5d, 80% interval 6.9–22.7d, P-based intervention comparison, recommends activate_alternate, support strong, shift 0.564 | MEASURED | artifacts/runs/latest/run.json (signed) |
| 22 | Inference latency ~7–11 ms/case mean (budget 50 ms) | MEASURED | court latency block (excluded from receipt id) |
| 23 | Neural transformer candidates at paper scale | NOT BUILT (honest wall W1) | HONEST_REMAINING_WALLS.md |
| 24 | External execution remained false; no secrets requested; no external actions | VERIFIED | boundary preserved throughout; receipts state external_execution=false |

## Gate outputs (final run)
- pytest: 128 passed
- prediction court: CONTAMINATION_DETECTED=false · LEAKAGE_DEFENDED=true · BENEFICIAL_CANDIDATE_PROMOTED=true · ATTRACTIVE_REGRESSION_REJECTED=true
- fixture: POSTERIOR_ABSTAINED=false · SUPPORT_STATE=strong · RECOMMENDED_INTERVENTION=activate_alternate
- python verifier: POSTERIOR_VERIFIED=true · EVIDENCE_ROOM_VERIFIED=true
- node verifier: posterior_verified:true · verified:true
- governance: ACTION_STATUS=approved_shadow (dual control intact)
- legacy benchmark court: BENEFICIAL_MUTATION_PROMOTED=true · HARMFUL_MUTATION_REJECTED=true
- semantic check: 23/23 true · DIGITAL_TWIN_SEMANTIC_PASS

## Reproduce
```
python3.11 -m venv .venv && .venv/bin/pip install -e '.[dev]'
make check          # runs tests + prediction court + fixture + both verifiers + governance + benchmark + semantics
make run            # cockpit at http://127.0.0.1:8765 (visual gate W3)
```
