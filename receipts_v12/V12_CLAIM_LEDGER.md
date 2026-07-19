# V12 CLAIM LEDGER (delta over V11)
| Area | Claim | Class | Evidence |
|---|---|---|---|
| Default posture | no arming config ⇒ UNARMED; unarmed executor refuses all | MECHANICALLY VERIFIED | gate stages 1,10-11; tests |
| Arming | dual authorizers + pinned signature + window + allowlist + budget; tamper unarms | MECHANICALLY VERIFIED | test_unarmed_default_and_tamper; gate 3-4 |
| Custody interlock | production arming refused without VERIFIED production custody | MECHANICALLY VERIFIED | test_production_arming_requires_custody; gate 2 |
| Action licenses | single-use, expiring, signed, binding action+evidence+approval+arming | MECHANICALLY VERIFIED | test_license_single_use_binding_and_expiry; gate 6-8 |
| Proof chain | receipt binds principal/evidence/approval/arming/license/adapter/outcome, content-hashed + signed | MECHANICALLY VERIFIED | test_full_action_chain…; gate 5 |
| Reversal | compensating record bound to original receipt hash | MECHANICALLY VERIFIED | gate 9; tests |
| Budget | max_actions enforced | MECHANICALLY VERIFIED | test_full_action_chain… |

## Boundary
Real external execution: NOT ESTABLISHED, DISABLED. Rehearsal actions are
synthetic/local/reversible. EXTERNALLY VALIDATED: nothing. external_action=false.
