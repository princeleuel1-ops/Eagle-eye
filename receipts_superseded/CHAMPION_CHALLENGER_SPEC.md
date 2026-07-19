# Champion–Challenger Specification (eagle-eye-sealed-evolution/1.0)

- Mutation surface: MUTATION_WHITELIST.json (typed grids only; off-whitelist mutation raises;
  widening the whitelist itself requires existing dual-control governance).
- Candidate identity: cand-sha256(parent, diff, cycle)[:12]; carries parent_champion_id,
  hypothesis, expected benefit, known risk, generation_seed, dataset_snapshot_id,
  court_release_id, budget position.
- Determinism: (parent, snapshot, seed, budget, court release) -> identical candidate
  sets and evaluation order (test-locked).
- Promotion states: PROMOTED / REJECTED / ABSTAINED_INSUFFICIENT_EVIDENCE /
  BLOCKED_TRUST_REGRESSION / BLOCKED_CALIBRATION_REGRESSION / BLOCKED_SHIFT / BLOCKED_CONTAMINATION.
- Precommitted gate order (fail-closed): contamination -> leakage -> dev pre-screen
  (no alpha spent on dev losers) -> min effective sample (scored>=30) -> trust gates
  (standard abstention 0; probes refused; permutation <= 0.05) -> coverage band [0.70,0.92]
  AND distance-to-nominal non-worsening (+0.02 max) -> temporal OoD non-worse vs champion
  -> sealed NLL improvement AND CRPS non-worsening (+0.002 tolerance) vs sitting champion.
- A statistically attractive candidate that weakens any trust surface is BLOCKED, not promoted.
- Lineage: every decision chains previous_lineage_hash; full chain replayable
  (EVOLUTION_LINEAGE.json, verified每 cycle and at close).
