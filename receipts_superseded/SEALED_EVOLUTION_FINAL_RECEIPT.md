# Sealed Evolution Final Receipt

Benchmark receipt: sevo-55beb4e85754 · spec sealed-evolution-benchmark/1.0

## Executed claim (supported by evidence)
SIX consecutive sealed evolution cycles in which every committed prediction, resolved
outcome, immutable score, registry-growth decision, challenger evaluation, promotion,
rejection, and guarantee suspension chains to canonical signed receipts that were replayed
and verified every cycle, with ZERO trust-boundary regressions and ZERO receipt
verification failures. external_action=false throughout.

## Recursive proof (genuine, not manufactured)
- PROMOTED: cand-607411a7dc5f (governor.shift_suspect 0.80 -> 0.90), cycle 5.
  Mechanism: flywheel registry growth added post-shift resolved tasks to the prior pool,
  making the [0.80,0.90) widening band over-conservative. Passed ALL precommitted gates:
  dev NLL 0.6789 < champion 0.6932; sealed holdout NLL 0.8262 better than same-registry
  champion; coverage 0.9091 in band, distance-to-nominal within +0.02; temporal-OoD
  non-worse; permutation 0.0; probes refused. Conformal suspension threshold (0.80) is a
  SEPARATE fail-closed layer and is unchanged.
- REJECTED (17): includes dev-attractive candidates rejected without holdout looks and,
  in the pre-repair run, two dev-attractive candidates BLOCKED_SHIFT — the gate class
  demonstrated live. First-run receipts preserved in the lineage history of that run.

## Cycle log
N attempted 6 · N completed 6 · promotions 1 · rejections 17 ·
abstentions 0 · trust regressions 0 · coverage failures 1
(cycle 4, first post-shift target — honest miss) · shift suspensions 2
(cycles 5-6, conformal fail-closed) · off-policy non-identifiable 0 ·
registry growth +6 tasks · receipt verification failures 0.

## Final one-shot audit holdout (seed 909, single recorded look)
NLL 0.881721 · CRPS 0.32857 ·
coverage80 0.863636 · standard abstentions 0 · probes refused: True

## Trust boundaries after evolution
All 167 tests green including the pre-existing 128; both verifiers green on the signed
evidence room; dual-control, audit chain, identity, policy pinning, tenancy: unchanged
and re-executed. No gate was weakened to earn the promotion.

## Repairs during this build (falsify -> repair -> re-verify)
- F9 stale champion caches under registry growth (unfair cross-registry comparisons):
  fixed via update_registry() cache invalidation; the promotion above occurred only
  under fair same-registry comparison.
- F10 challenger budget wasted on no-op mutations (seq.* while base=set_mt): no-op guard.
