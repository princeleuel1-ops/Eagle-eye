# Multiple-Comparison Defense Policy

Primary defenses (carry the real weight):
1. immutable dataset snapshots (snapshot id binds registry manifest + partition seeds)
2. precommitted metrics and thresholds (spec above; no post-hoc gate edits)
3. challenger budget: 3 per cycle, hard cap
4. development pre-screen: dev non-improvers are rejected WITHOUT a holdout look
5. holdout access ledger: every promotion-holdout look recorded with accessor identity
6. contamination fingerprints between partitions (id + content + seed distinctness)
7. final audit holdout: zero candidate-generation access; exactly one recorded look at close
8. minimum effective sample gate (scored_count >= 30)

Alpha ledger: flat spend 0.0025 (=0.05/20) per challenger holdout look; run halts new looks
when exhausted (ABSTAINED_INSUFFICIENT_EVIDENCE). Executed run: 18 candidates proposed,
17 rejected pre-holdout, 1 charged look, alpha spent 0.25% of 5.00%.

HONESTY: alpha spending does NOT eliminate Goodharting; it prices holdout looks. The sealed
final audit holdout and precommitted gates are the primary defense. Holdout retirement policy:
promotion holdout must be rotated (new seed, fingerprint-checked) after alpha exhaustion or
20 looks, whichever first; retired holdouts never return.
