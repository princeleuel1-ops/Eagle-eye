# V6 HONEST REMAINING WALLS — Eagle Eye Zenith Pilot Forge

Supersedes all prior walls documents. Closed walls cite closing evidence;
open walls are stated plainly with no softening. V6 turns several V5 "seams"
into working LOCAL REFERENCE implementations — that is emphatically NOT the
same as establishing the production capability.

## Newly built in V6 as LOCAL REFERENCE (mechanically verified) — but production still NOT ESTABLISHED

- **Durable storage** → a real transactional, append-only, tenant-bound
  SQLite backend with migrations and verified backup/restore EXISTS and is
  tested. **Production database (PostgreSQL) NOT ESTABLISHED** — the Postgres
  config shape fails closed without a reachable server; SQLite is a pilot
  reference, not production infrastructure.
- **Identity** → signed assertion verification with issuer/audience/tenant/
  exp/nbf/revocation and dual control EXISTS and is tested against a labeled
  local dev issuer. **Production OIDC/identity NOT ESTABLISHED** — the OIDC
  shape fails closed without external configuration; no production IdP is
  wired or verified.
- **Key custody** → a sign/verify/rotate/health provider interface with local
  ephemeral and encrypted-persisted providers EXISTS. **Production KMS/HSM NOT
  ESTABLISHED** — AWS/GCP shapes are `DISABLED_NO_CREDENTIALS` and refuse to
  sign; no cloud adapter may claim success without a real remote signature
  verification test, and none exists here.
- **Evaluator isolation** → a real separate OS-process boundary with the
  secret confined to the evaluator process, durable charged looks, and
  crash/restart no-refund semantics EXISTS and is tested by killing the real
  process. **Organizational/host isolation NOT ESTABLISHED** — this is
  process isolation on ONE host in ONE trust domain; it is not multi-party or
  organizational separation, which cannot be established inside one host by
  construction.
- **Durable external transparency store** → the local head-commitment table
  is append-only and separately persisted from the rows. **An externally
  durable, third-party-reproducible transparency service NOT ESTABLISHED** —
  the AuditSink production seam remains fail-closed.
- **External execution** → the full shadow lifecycle EXISTS with a fail-closed
  executor. **Real external execution NOT ESTABLISHED and intentionally
  DISABLED** — the only wired executor raises `AdapterDisabled`; enabling a
  real one is a separate, explicitly authorized decision outside this build.

## Carried open walls (unchanged truths — stated plainly)

- **W1 — No neural transformer trained.** Algorithmic empirical-Bayes analogs
  behind the same interface. Scale-up path unchanged.
- **W2 — Everything is synthetic.** Two synthetic generator families; NO
  live-data evidence anywhere. Fixture tenants are labeled `FIXTURE`
  end-to-end so they cannot be mistaken for customer records.
- **W-transfer — Champion advantage does NOT survive a structurally
  independent generator** (CI straddles zero); in-family CRPS transfer NOT
  ESTABLISHED. Calibration transfers; accuracy advantage does not.
- **W-promotion — promotions are rare, small, per-run**; cross-run alpha is
  NOT pooled (rerun-lottery guard is procedural/auditable via the ledger, not
  statistical).
- **W-confounding — No sensitivity model for unobserved confounding.**
- **W-timeout — evaluator SIGALRM path is main-thread only**; the pilot
  service instead uses per-reservation deadlines + a restart sweep for
  wall-clock enforcement (documented, tested).
- **W-power-model — the power analysis is MODEL-CONDITIONAL** (bootstrap over
  an empirical null from one synthetic generator).

## Honest scope of the V6 numbers

- Test/gate counts (314 tests across 40 files, 25 gates) and failure-court counts (39 cases)
  are MECHANICALLY VERIFIED by execution.
- Performance numbers are a LOCAL SYNTHETIC workload on one sandbox host, for
  regression tracking only — NOT an operational-scale or SLA claim.
- The main sealed run is receipt-bound; if it is vacuous it is labeled
  `VACUOUS_INTEGRITY_ONLY` and never promoted to a universal full-replay claim.

## What a real pilot still needs (see PILOT_OPERATOR_RUNBOOK.md §Onboarding)

Authorized tenant data feed · PostgreSQL (or equivalent) with the same
interface · KMS/HSM key custody · SSO/OIDC identity · durable append-only
external transparency store · legally/operationally cleared external execution
— each wired to its named seam and INDEPENDENTLY verified before any live
claim. **EXTERNALLY VALIDATED: nothing.**

## Boundary

Nothing in this build was pushed to a remote, merged into the Mac's `main`, or
deployed. V6 is an isolated source + patch handoff for independent local
verification. The sandbox cannot see `/Users/Apple/...`; no claim here depends
on it.
