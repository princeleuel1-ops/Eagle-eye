# V7 HONEST REMAINING WALLS

Supersedes `receipts_v6/V6_HONEST_REMAINING_WALLS.md` as the current walls
document. Every V6 wall is restated; one is upgraded with its closing
evidence; nothing else moved.

## Changed by V7

- **W-promotion (upgraded, not deleted).** V6: "promotions are rare, small,
  per-run; cross-run alpha is NOT pooled (rerun-lottery guard is
  procedural/auditable, not statistical)."
  V7: cross-run evidence IS now pooled by an anytime-valid e-process per
  exact config pair (sign null, binomial mixture e-values, Ville-bounded at
  pre-registered α = 0.05). The rerun-lottery guard is now STATISTICAL —
  optional stopping and continuation cannot inflate error — with these
  honest qualifications, stated plainly:
    - THEOREM-CONDITIONAL on independent case sampling within and across
      runs; the CSPRNG synthetic suite generator provides this BY
      CONSTRUCTION, so on synthetic data the condition is real. No live-data
      analog exists (W2 stands).
    - The pooled null is the paired SIGN null (median-beat), deliberately
      heavy-tail-immune. It is a DIFFERENT, weaker-assumption hypothesis
      than the per-run mean-NLL CLT test; the per-run gate chain is
      unchanged and still the only path to a per-run PROMOTED state.
    - A crossing is promotion EVIDENCE on the synthetic suite distribution —
      it does not bypass gates, establish transfer, or claim live value.
    - As of this receipt set, whether any stream has crossed is a per-run,
      receipt-bound finding; the gate never requires one.

## Carried open walls (unchanged truths — stated plainly)

- **W1 — No neural transformer trained.** Algorithmic empirical-Bayes analogs
  behind the same interface.
- **W2 — Everything is synthetic.** NO live-data evidence anywhere.
- **W-transfer — Champion advantage does NOT survive a structurally
  independent generator** (CI straddles zero); in-family CRPS transfer NOT
  ESTABLISHED. The V7 feedback harness optimizes exploration IN-FAMILY; it
  neither tests nor claims alien-generator advantage.
- **W-confounding — No sensitivity model for unobserved confounding.**
- **W-timeout — evaluator SIGALRM path is main-thread only** (pilot uses
  per-reservation deadlines + restart sweep).
- **W-power-model — the power analysis is MODEL-CONDITIONAL.** The V7 null
  and power batteries are likewise synthetic, seeded regression pins — they
  verify the implemented rule's operating characteristics, not a claim about
  any external world.
- **Production capabilities** — database, KMS/HSM, OIDC, durable external
  transparency, organizational isolation, real external execution: all
  remain fail-closed seams or labeled local references. NOT ESTABLISHED.
- **General self-improvement — NOT ESTABLISHED and NOT CLAIMED.** V7 adds a
  bounded, whitelisted, replay-verified learning loop over 7 typed
  parameters. It cannot modify its own code, gates, whitelist, budgets, or
  statistics; it reweights exploration inside a fixed space and accumulates
  evidence under a fixed pre-registered rule. Calling that "general
  self-improvement" would be false; we do not.

## Honest scope of the V7 numbers

Test and gate counts on this tree are mechanically verified by execution
(see `V7_GATE_RESULTS` in the delivery folder). Ledger standings and any
crossings are receipt-bound per run-set. Performance remains a local
synthetic regression track only.

**EXTERNALLY VALIDATED: nothing.**

## Boundary

Nothing here was pushed to a remote, merged into the Mac's `main`, or
deployed; external execution stays disabled. V7 is an isolated source +
patch handoff on top of the user's authoritative V6 merge, for independent
local verification on the canonical machine.
