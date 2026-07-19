# V7 — RECURSIVE SEALED EVOLUTION
## Anytime-valid cross-run promotion ledger + verified feedback harness

Baseline: the user's Mac-verified V6 merge (tree `e2b1e136…`, archive SHA-256
`921f2805…`), 25/25 gates. Everything below is ADDITIVE on that baseline.

## 1. The SOTA gap, in this repository's own words

The V6 walls and claim ledger state it exactly:

- **W-promotion** — "promotions are rare, small, per-run; cross-run alpha is
  NOT pooled (rerun-lottery guard is procedural/auditable via the ledger, not
  statistical)." Evidence for a genuinely better challenger DIED at every run
  boundary. Running again could never build a case — and a lucky run could
  not be statistically told apart from many retries.
- **Blind generation** — `generate_candidates` sampled the mutation whitelist
  UNIFORMLY at random. Promotions, near-misses, and blocks left no trace on
  the next run's search. The flywheel spun; it did not climb.

That is the bottleneck this increment attacks. Not by weakening a single
gate — by giving the system a mathematically sound memory.

## 2. The instrument

### 2a. E-process promotion ledger (`src/eagle_eye/eprocess.py`)

One e-process (test supermartingale) per evidence stream, a stream being an
exact (champion_config, challenger_config) pair.

- **Null hypothesis per stream:** on a fresh sealed case, P(challenger's
  per-case NLL strictly beats champion's) <= 1/2 — the paired sign null.
- **Per-run evidence:** wins/losses/ties recomputed FROM THE REVEALED BUNDLE
  by the ledger itself — suite rebuilt from the revealed secret and checked
  against the pre-run commitment, registry trajectory rebuilt through the
  recorded grown tasks, per-case NLL diffs micro-quantized. Nothing is
  copied from the run's own aggregates; a recomputed pair count that
  disagrees with the recorded `n_paired` aborts admission.
- **Per-run e-value (exact closed form):**
  `e(k, m) = 2^(m+1) · B(k+1, m−k+1) · (1 − I_{1/2}(k+1, m−k+1))`
  — the one-sided binomial mixture e-value, uniform prior on theta ∈ (1/2, 1].
  At the null boundary its expectation is EXACTLY 1 (enumeration-tested);
  for every theta <= 1/2 it is <= 1 (MLR argument, enumeration-tested).
- **Cross-run pooling:** log e-values ADD across admitted runs (integer
  micro-nats). Fresh CSPRNG secrets make runs independent, so the running
  wealth is a test supermartingale and Ville's inequality gives
  `P_H0(∃R: W_R ≥ 1/α) ≤ α` — TIME-UNIFORM Type-I control, valid under
  optional stopping and optional continuation.
- **Within-run dependence guard:** a run's promotion suite is fixed once its
  secret is drawn, so only the FIRST sealed look per stream per run
  contributes; later same-pair looks that run are recorded non-contributing.
- **Promotion evidence threshold:** cumulative log-e ≥ ln(1/α) with
  pre-registered α = 0.05 (`EPROCESS_LOG_THRESHOLD_MICRO = 2_995_732`).

**Why this closes the rerun lottery BY CONSTRUCTION:** under H0 the wealth
process is a supermartingale — rerunning forever still crosses 1/α with
probability ≤ α. Under a true advantage, evidence accumulates run over run
until it crosses. Retrying helps exactly and only when the challenger is
actually better. The V6 procedural guard is now a theorem.

### 2b. Verified feedback harness (`src/eagle_eye/feedback.py`)

A signed FeedbackState of integer pseudo-weights over the EXISTING mutation
whitelist:

- **Pure update** from REVEALED, replay-verified outcomes only:
  PROMOTED +5 · sealed-better-but-not-significant +2 · BLOCKED −2 (floored)
  · positive-evidence stream +1. Input state never mutated; weights never
  fall below the exploration floor (no starvation, mode-collapse guard).
- **Deterministic weighted generation** (`weighted_generate_candidates`):
  same whitelist, same grids, same budget, same skip rules — only the
  exploration DISTRIBUTION changes. The generation seed and every candidate
  id bind the state's sha256, so replay recomputes generation bit-for-bit
  and any state substitution changes every downstream id.
- **Contamination-closed:** the state consumed by run N is hash-fixed before
  run N's secret exists; only runs 1..N−1's revealed bundles fed it. A run
  cannot steer its own generation.

### 2c. The recursive loop (`scripts/run_recursive_evolution.py`)

RUN (sealed, fresh secret) → VERIFY (independent full-decision replay in a
child process; zero mismatches required) → ADMIT (fail-closed e-process
ledger, self-recomputed evidence) → LEARN (pure state update, signed
transition) → next round. The loop learns only from what it has proved.
Every round row and every admission is a signed chain row; the receipt binds
bundle hashes, replay verdicts, state hashes, ledger state hash.

## 3. What a crossing means — and what it does not

A stream crossing 1/α is a THEOREM-CONDITIONAL statistical evidence claim:
"on this synthetic sealed-suite distribution, this exact config pair's
challenger beats the champion on more than half of cases, at anytime-valid
level α," conditional on independent case sampling (which the CSPRNG suite
generator provides synthetically). It is NOT: a per-run gate bypass (the
V6 gate chain is untouched and still binding), an alien-generator claim
(W-transfer stands), a live-data claim, or external validation (still
NOTHING externally validated).

`RECURSIVE_EVOLUTION_PASS` NEVER requires a crossing. At small round counts
the honest common outcome is `NO_STREAM_CROSSED_PROMOTION_EVIDENCE_THRESHOLD`
— reported as such, exactly like `NO_CHALLENGER_EARNED_PROMOTION` before it.

## 4. Standing prohibitions honored

No gate lowered, no tolerance widened, no test weakened or deleted. All
changes additive; legacy paths bit-identical (feedback_state=None everywhere
pre-existing; legacy bundles carry no feedback block and replay through the
identical pre-V7 branch — the pinned battery fixture is untouched).
`external_action=false` throughout; external execution remains disabled.
