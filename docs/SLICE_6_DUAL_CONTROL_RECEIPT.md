---
type: verification_receipt
title: Eagle Eye Zenith Slice 6 — Dual-Control Shadow Approval
timestamp: 2026-07-12
---

# Executable claim

Eagle Eye can request and approve a tenant-scoped Action Contract under dual-control invariants while guaranteeing fixture approvals remain shadow-only and execute nothing externally.

# State machine

```text
pending_approval
→ awaiting_independent_approval
→ approved_shadow
```

Production execution is not part of this state machine.

# Required identities

Requester:

- non-empty principal ID;
- matching tenant;
- `analyst` role.

Approver:

- non-empty principal ID;
- same tenant as action and request;
- `approver` role;
- different principal from requester.

# Positive proof

```text
GOVERNANCE_ACTION=action-bce5ceb7b8a2
DUAL_CONTROL_VERIFIED=true
GOVERNANCE_TENANT_VERIFIED=true
SHADOW_ONLY=true
ACTION_STATUS=approved_shadow
APPROVAL_RECEIPT_ID=approval-4dbc5cf6f4fe
```

The receipt binds:

- request ID;
- action ID;
- tenant ID;
- requester ID;
- approver ID;
- evidence IDs;
- action status;
- external-execution state;
- dual-control result;
- tenant result.

# Negative proofs

Tests prove rejection of:

1. self-approval, even when the principal holds both roles;
2. cross-tenant approval;
3. approval by a principal lacking the `approver` role;
4. requests by a principal lacking the `analyst` role;
5. actions not in `pending_approval` state.

# Product integration

`/api/governance` exposes the fixture governance receipt to the command surface. The Action Contract panel explicitly displays:

```text
GOVERNANCE HARNESS · APPROVED_SHADOW
DUAL CONTROL · TRUE
EXTERNAL EXECUTION · FALSE
approval-4dbc5cf6f4fe
```

This harness is visually separate from the actual Action Contract, which remains pending and disabled in fixture mode.

# Full gate

```text
23 passed
SIGNER_TRUSTED=true
TENANT_VERIFIED=true
DUAL_CONTROL_VERIFIED=true
GOVERNANCE_TENANT_VERIFIED=true
SHADOW_ONLY=true
HAS_GOVERNANCE_HARNESS=true
EAGLE_EYE_ZENITH_CHECK_PASS
```

# Browser verification

- Governance status visible in Action Contract panel.
- Receipt ID visible.
- External execution false visible.
- Strict CSP remains active.
- Zero browser console messages.
- Zero JavaScript errors.

# Brittle point

Principals are authorized fixture dictionaries supplied directly to the governance engine. The state machine proves authorization invariants but does not authenticate those principals. Production requires a trusted identity provider, short-lived sessions, server-side role resolution, revocation, rate limits, and an append-only audit store.
