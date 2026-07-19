# V12 — LICENSED EXECUTION SPINE
Base: V11 tree fe25149e (32 gates / 419 tests). Additive. Final rung.

## The wall, verbatim
"Real external execution NOT ESTABLISHED and intentionally DISABLED — the
only wired executor raises AdapterDisabled; enabling a real one is a
separate, explicitly authorized decision outside this build."

## The instrument (src/eagle_eye/licensed_execution.py)
- UNARMED by default; NullActionExecutor posture untouched everywhere else.
- Signed ExecutionArmingConfig: pinned out-of-band key, dual distinct
  authorizers, action-class allowlist, max_actions budget, validity window.
  production arming ADDITIONALLY demands VERIFIED production custody (V11
  interlock, in code) — unreachable in-repo by construction.
- Per-action single-use license: signed token binding action_id + evidence
  digest + approval receipt + arming config hash; TTL 15 min; spent-token
  ledger. Replay/tamper/mismatch/expiry ⇒ ExecutionRefused.
- LocalOutboxAdapter: THE concrete reversible adapter — signed records to a
  local outbox (no network); reverse() emits a compensating record bound to
  the original receipt hash.
- The receipt binds the complete proof chain: principal → evidence digest →
  approval → arming sha → license sha → adapter attestation → outcome →
  reversal handle; content-hashed and signed.

## Gate 33 (execution-rehearsal): 11 stages sealed green
unarmed default; production-needs-custody; single-approver refused; fixture
arming; THE FIRST (fixture) ACTION with full proof chain to the outbox;
license single-use; tampered license; non-allowlisted class; reversal binds;
unarmed executor refuses. PRODUCTION_EXECUTION_REACHABLE=false, network
false.

## Honest boundary
Real external execution remains NOT ESTABLISHED and DISABLED. The rehearsal
action is synthetic, local, reversible, and labeled. The first real action
requires the FIRST_ACTION_RUNBOOK ceremony on real authority, custody, and
an operator-built production adapter. EXTERNALLY VALIDATED: nothing.
