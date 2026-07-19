# Sealed Evolution Flywheel — Architecture (as built)

```
commit_cycle_prediction (champion config; commitment = quantize-micro hash)
  -> PredictionLedger.commit_prediction        [outcome_resolution.py]
  -> PredictionLedger.resolve                  immutable scoring vs COMMITTED dist;
       off-policy identifiability checks; append-only hash chain
  -> grow_registry_task -> build_registry      eligible outcomes only; new release id;
       controller.update_registry              (invalidates champion eval caches — F9)
  -> EvolutionController.propose_candidates    typed whitelist, deterministic, budgeted
  -> EvolutionController.decide                dev pre-screen -> alpha-charged sealed
       holdout look -> precommitted gates:
       trust (abstention/support/permutation) > calibration (band + distance-to-nominal)
       > shift (OoD non-worse) > sealed improvement vs sitting champion
  -> signed lineage receipt                    chains parent champion receipt, snapshot,
       court release, policy release, previous lineage hash
  -> conformal wrapper                         [conformal.py] split-conformal quantile from
       the CALIBRATION partition; guarantee-state machine; suspension preserves last receipt
  -> value_of_information                      [voi.py] exact conjugate preposterior;
       signed loss; MODEL_CONDITIONAL_ESTIMATE labeling for t posteriors
  -> cockpit /api/evolution                    state.json; honest claim gating
  -> verification replay                        ledger chain + lineage chain + commitment
       recompute + registry manifest recompute, every cycle
```

Sealed partitions (immutable identities): development seed 11 (candidate feedback),
calibration seed 31 (conformal only), promotion holdout seed 202607 (alpha-charged looks),
final audit holdout seed 909 (exactly ONE look, after the last cycle).

Files: outcome_resolution.py, evolution.py, conformal.py, voi.py,
scripts/run_sealed_evolution.py, web/evolution.js (+server /api/evolution, semantics, Makefile).
Existing trust stack untouched: identity, policy, governance, audit, evidence, verifiers.
