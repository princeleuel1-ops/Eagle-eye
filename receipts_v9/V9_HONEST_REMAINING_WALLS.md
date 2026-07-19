# V9 HONEST REMAINING WALLS

Supersedes `receipts_v8/V8_HONEST_REMAINING_WALLS.md` as the current walls
document. One wall upgraded with closing evidence; nothing else moved.

## Changed by V9

- **External transparency (upgraded, not deleted).** Before: every verifier
  imported the code whose claims it checked — third-party verification was
  circular by construction. Now: `verifier_standalone/` is a single-file,
  stdlib-only, `python3 -I`-runnable verifier proving authenticity,
  integrity, commit-reveal, accounting, decision-rule reproduction, and
  evidence arithmetic with ZERO repository trust, plus an offline
  hash-chained heads log. The circularity is broken — as an INSTRUMENT.
  Still open, stated plainly:
    - Semantic replay (suites rebuilt from revealed secrets, predictions
      re-scored) remains code-bound to the hash-pinned tree.
    - An externally OPERATED, durable transparency service does not exist;
      the heads log is offline and its tail is only as immutable as its
      newest externally pinned hash.
    - **No third party has run any of it. EXTERNALLY VALIDATED: nothing.**

## Carried open walls (unchanged — stated plainly)

- **W1 — No neural transformer trained.**
- **W2 — Everything is synthetic.** No live-data evidence anywhere.
- **W-transfer — measured by a replayable court (V8), still NOT
  ESTABLISHED**: champion advantage dies on the structurally-independent
  generator axis, CRPS-first; localization receipted, transfer not earned.
- **W-confounding · W-timeout · W-power-model** — unchanged.
- **Production capabilities** (database, KMS/HSM, OIDC, organizational
  isolation, real external execution) — fail-closed seams or labeled local
  references. NOT ESTABLISHED.
- **General self-improvement — NOT ESTABLISHED and NOT CLAIMED.**
- **Live pilot, revenue, customer value — NOT ESTABLISHED** (per the
  project's own build report).

## Boundary

Nothing merged, pushed, armed, or executed from this build. The V9 series
applies onto the V8 tree; the merge — and the first stranger — are the
user's to choose.
