# SOTA Gap and Brittle Point Map — Eagle Eye Zenith Run

Sources: direct inspection of `project/src` (all 14 modules read), paper digest
(`analysis/PAPER_DIGEST.md`, from arXiv:2606.20538v1 + official code), strategy
digest (`analysis/STRATEGY_DIGEST.md`), mission docs. Every claim below is
traceable to one of those.

## Candidate gaps investigated

### G1 — Prior-relevant task selection vs mere similarity
- mechanism: retrieval by feature similarity can select tasks that are similar but causally different (adversarial similarity)
- best known in sources: paper selects prior tasks BY CONSTRUCTION (same generative λ); official code has no real selector
- why it fails here: production registries mix regimes; similarity ≠ shared latent regime
- load-bearing assumption: disruption_class + lane/region features correlate with hidden regime
- brittle point: two regimes share disruption_class across a temporal shift boundary (regime-port-congestion-a vs -shifted)
- cheapest falsification: court attack `adversarial_similar` — same class, shifted regime priors; measure negative transfer vs no_prefix
- repair candidate: shift governor downgrade + temporal recency in selection
- leverage if closed: HIGH (selection quality bounds everything downstream)

### G2 — Temporal / target leakage
- mechanism: future info entering an earlier prediction (as_of violations, target obs pooled into prior)
- best known: paper N/A (synthetic); existing Eagle Eye has as-of discipline in fixtures only
- why it fails here: registry + selector + compiler each add a leak surface
- brittle point: compiler accepting a task whose as_of_end postdates cutoff
- falsification: RED tests injecting leaky/foreign tasks (implemented: `test_compiler_refuses_leaky_prior_task`, `test_as_of_boundary_excludes_future_and_foreign_tenants`) — PASS (fail-closed)
- leverage: HIGH, cheap to close (closed in Slices C–D)

### G3 — Calibrated heavy-tail prediction under sparse target evidence
- mechanism: K prior tasks must supply the prior mass when n_target ∈ {0,1,2}
- best known: paper shows prior value greatest at low target counts; degrades gracefully as n grows
- why it fails here: wrong variance decomposition (τ² vs σ²) produces over/under-confidence; heavy-tail regimes (df=3) break normal assumptions
- brittle point: τ̂² = max(ε, between − σ̂²·mean(1/n)) can hit the floor and collapse spread
- falsification: scarcity sweep + heavy-tail holdout cases; coverage@80 gate in court
- repair: Student-t predictive with df tied to effective K (implemented); governor widening
- leverage: HIGH — this is the primary user-facing quantity

### G4 — K/context extrapolation cliff
- mechanism: paper: model trained K∈[0,10] fine at K=10, KL 0.0014→0.031 at K=20 (22x worse)
- why it matters here: operators will feed more history assuming more is better (invariant 6)
- brittle point: candidate silently accepting K beyond validated support
- falsification: court K-sweep beyond declared `training_support.k_range`; governor must abstain (implemented: `test_governor_abstains_beyond_validated_k`) — PASS
- leverage: MEDIUM-HIGH (governance surface, cheap)

### G5 — Order sensitivity vs permutation-aware aggregation
- mechanism: sequential prefix models are order-sensitive; paper measures small IID sensitivity (KL 0.005±0.004) but ERA5 OOD reversal (val NLL −2.06 → test +7.13) hits the sequential variant hardest
- brittle point: recency weighting helps under drift, catastrophically misleads when order is arbitrary
- falsification: court permutation battery (R deterministic shuffles; spread gate); implemented at candidate level (`test_set_mt_is_permutation_invariant_and_seq_prefix_is_not`) — PASS
- leverage: HIGH for OOD honesty

### G6 — Useful transfer vs negative transfer under regime shift
- mechanism: priors from a pre-shift regime bias post-shift targets (ERA5 warning)
- brittle point: selector has no shift detector; only the governor sees the discrepancy
- falsification: temporal OoD split (post-2025-07 targets with pre-shift priors) in sealed holdout
- repair: shift_score widening; honest downgrade rather than silent confidence
- leverage: HIGH — this is the central deployment risk named by the paper

### G7 — Binding stochastic outputs to reproducible evidence receipts
- mechanism: a verifier must recompute every commitment (distribution params → canonical hash) from run.json alone
- best known: existing evidence room binds deterministic scenario data; no probabilistic commitments exist
- brittle point: floating-point canonicalization drift between Python and Node
- falsification: parity + tamper tests in both runtimes (planned Slice G)
- leverage: HIGH — this is Eagle Eye's differentiation

### G8 — Recursive improvement without contamination/Goodharting
- mechanism: dev/holdout separation with content fingerprints (exists), promotion demands sealed improvement + non-regression
- brittle point: an IID-attractive candidate (tuned on dev) promoting on dev alone
- falsification: engineered `seq_prefix_overfit` candidate expected to win development, fail sealed OoD gate (planned Slice F)
- leverage: MEDIUM-HIGH (proves the court's teeth)

## Selection

- PRIMARY GAP: **G3+G6 combined — calibrated prior transfer under scarce target evidence that remains honest under regime shift** (they share one mechanism: correct variance decomposition + shift governance). This controls the build sequence: registry → selector/compiler → candidates → sealed court with temporal OoD.
- SUPPORTING: **G7** (evidence binding of stochastic outputs; Slice G) and **G8** (court teeth via engineered rejection; Slice F).
- G2/G4/G5 are closed structurally by construction and locked by tests already green.

## Brittle points ledger (live)

| # | Brittle point | Guard |
|---|---|---|
| B1 | τ̂² floor collapse under homogeneous priors | MIN_TAU + coverage gate in court |
| B2 | compiler accepting post-cutoff prior tasks | CompilerError + RED test (green) |
| B3 | seq_prefix under arbitrary order | permutation battery + set_mt default |
| B4 | pooling drowning target evidence | mechanism test (green) + court NLL gap |
| B5 | K beyond validated support | governor abstain + RED test (green) |
| B6 | py/node float canonicalization drift | parity test on identical bytes (Slice G) |
| B7 | dev-tuned candidate Goodharting the court | sealed holdout + engineered rejection (Slice F) |
| B8 | heavy-tail (df=3) regimes breaking normal candidates | holdout stress cases; honest scoring |
