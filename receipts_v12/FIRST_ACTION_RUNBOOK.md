# FIRST ACTION RUNBOOK — the V12 arming ceremony

The execution spine is READY and UNARMED. This is the ceremony for the first
real external action. It is deliberately heavier than every other ceremony:
this is the only one that touches the world.

## Preconditions (all four prior ceremonies + one)
- [ ] V10 data authority armed (LIVE_ACTIVATION_RUNBOOK) — the action must
      trace to real, authorized evidence.
- [ ] V11 custody VERIFIED on a production provider — production arming is
      REFUSED without it (interlock is in code, not policy).
- [ ] A reversible action class chosen and implemented against the adapter
      seam (the shipped LocalOutboxAdapter is the reference; a real adapter
      is deployment-specific and must implement reverse()).
- [ ] Two arming approvers; one action-license issuer.

## The ceremony
1. Sign the ExecutionArmingConfig (arming_class="production", action-class
   allowlist, max_actions budget — start with 1, validity window measured
   in hours) with your pinned authority key. Dual authorizers recorded.
2. Verify: verify_arming(...) with your custody descriptor must return
   ARMED_PRODUCTION with empty reasons.
3. For THE action: complete the normal shadow flow first (identity →
   evidence → dual-control approval). Then issue the single-use action
   license binding action_id + evidence digest + approval receipt + arming
   config hash. TTL 15 minutes.
4. Execute. The receipt binds the complete proof chain and is signed. Hand
   the receipt + bundle to the V9 stranger's verifier pipeline.
5. Verify the reversal path immediately after (reverse() on a sacrificial
   action first if the class allows).

## Abort switch
Expire/remove the arming config, revoke the authority key pin, or exhaust
max_actions ⇒ UNARMED, fail-closed. Licenses die alone in 15 minutes.

## What the first action means — and does not
One real action with a complete, stranger-verifiable proof chain is the
campaign's summit. It is still ONE action under a budget of one: not
operational scale, not autonomy at large, not external validation until a
stranger replays the receipt. The walls document stays in force.
