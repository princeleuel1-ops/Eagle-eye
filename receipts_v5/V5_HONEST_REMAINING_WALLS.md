# V5 HONEST REMAINING WALLS — Eagle Eye Zenith (canonical)

Supersedes all prior walls documents. Closed walls cite closing evidence;
open walls are stated plainly with no softening.

## Closed in V5 (new this release)

- **Setup portability under launcher contamination** → CLOSED. Preflight
  diagnostic (non-mutating, fail-fast `--strict`) + scrubbed pip/interpreter
  environment in the Makefile and gate runner. Tested with the exact Hermes
  `PYTHONPATH=/Users/Apple/.hermes/hermes-agent` value.
- **Cross-chain confusion under signer-key reuse** → CLOSED. Anchor
  `chain_id`/`run_id` are bound to every row and pinnable by callers, in both
  the Python and Node verifiers.
- **Verifier robustness on malformed key material** → CLOSED. Fails closed
  (`verified:False`) rather than raising.
- **Cockpit operator-trust gaps** → CLOSED (Lane 3): no raw-JSON inspector, no
  dead controls, no contradictory status pair, no single misleading proof
  badge, no mobile horizontal overflow — each locked by a browser assertion.
- **Replay-count precision** → CLOSED as a documentation defect: per-run
  counts are now explicitly bound to a specific run's machine-readable
  artifacts; no prose presents "3 decisions"/"4 decisions" as an invariant.

## Carried closed from V4 (re-verified in V5)

Browser gate executed (real Chromium); CSPRNG evaluator secret + lifecycle;
charge-before-execution; real full-decision replay + 19/19 mutation battery;
stratum-preserving power measurement; single evaluator-version constant +
mandatory dependency lock; complete package with all 113 PNGs.

## Open walls (unchanged truths — stated plainly)

- **W1 — No neural transformer trained.** Algorithmic empirical-Bayes analogs
  behind the same interface. Scale-up path unchanged.
- **W2 — Everything is synthetic.** Two synthetic generator families; NO
  live-data evidence anywhere. EXTERNALLY VALIDATED: nothing.
- **W-org — Evaluator independence is an in-process software boundary.**
  MECHANICALLY VERIFIED at the API level; organizational/host isolation NOT
  ESTABLISHED and unattainable inside one process by construction.
- **W-kms — Ephemeral in-run Ed25519 fixture keys.** No production KMS/HSM
  custody. The V5 `KeyCustody` adapter is a fail-closed seam, NOT a KMS.
- **W-identity — No production identity.** Requester/approver separation is
  exercised on fixtures; the `IdentityProvider` adapter is a fail-closed seam.
- **W-durable-audit — No external durable transparency store.** Audit chains
  are in-run + anchored; the `AuditSink` adapter is a fail-closed seam.
- **W-confounding — No sensitivity model for unobserved confounding.**
- **W-transfer — Champion advantage does NOT survive a structurally
  independent generator** (CI straddles zero); in-family CRPS transfer NOT
  ESTABLISHED. Calibration transfers; accuracy advantage does not.
- **W-promotion — promotions are rare, small, per-run**; cross-run alpha is
  NOT pooled (rerun-lottery guard is procedural/auditable via the ledger, not
  statistical).
- **W-timeout — TIMED_OUT looks use SIGALRM** (main-thread only); off-main
  callers get exception-based FAILED accounting, no wall-clock kill.
- **W-external-exec — No real external execution.** The `ActionExecutor`
  adapter is fail-closed; flipping the config flag without a real backend
  still refuses. Live execution requires separate explicit authorization.
- **W-neural / paper-scale** and **canonical-merge**: nothing merged; this is
  an isolated feature branch delivered for human-gated graft.

## What a real pilot still needs (see PILOT_READINESS_CHECKLIST.md)

Authorized tenant data feed · KMS/HSM key custody · SSO/OIDC identity ·
durable append-only transparency store · legally/operationally cleared
external execution — each wired to its named adapter and INDEPENDENTLY
verified before any live claim.
