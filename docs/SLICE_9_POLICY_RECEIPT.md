---
type: verification_receipt
title: Eagle Eye Zenith Slice 9 — Resource-Level Policy Decision Receipts
timestamp: 2026-07-12
---

# Executable claim

Verified identity and role membership are no longer sufficient to transition an Action Contract. A fail-closed policy decision point evaluates the exact principal, session, tenant, operation, resource state, execution mode, evidence set, and separation-of-duties context. Both request and approval transitions require an `ALLOW` decision, and both policy receipts are bound into the signed audit chain.

# Policy

```text
policy_id=eagle-eye-action-governance/1.0
```

Inputs:

- operation;
- principal ID;
- verified session ID;
- tenant ID;
- principal roles;
- expected action ID;
- Action Contract ID;
- Action Contract state;
- fixture/live mode;
- evidence IDs;
- requester ID for separation of duties.

# Fail-closed rules

Unknown operations are denied.

An action request requires:

- operation `request_action`;
- `analyst` role;
- matching tenant;
- matching resource ID;
- `pending_approval` state;
- at least one evidence ID;
- fixture mode.

An approval requires:

- operation `approve_action`;
- `approver` role;
- matching tenant;
- matching resource ID;
- `awaiting_independent_approval` state;
- at least one evidence ID;
- fixture mode;
- approver distinct from requester.

Live execution is explicitly denied by this policy version.

# Policy receipt

Every decision binds:

- policy version;
- effect (`ALLOW` or `DENY`);
- operation;
- principal ID;
- verified session ID;
- tenant ID;
- resource ID;
- SHA-256 digest of the exact resource state;
- deterministic reason codes;
- deterministic receipt ID.

# Adversarial proofs

Tests prove `DENY` for:

1. missing required role;
2. cross-tenant resource access;
3. self-approval;
4. missing evidence;
5. stale or invalid resource state;
6. live-mode execution attempt;
7. resource-ID mismatch;
8. unsupported operation.

Additional tests prove:

- an `ALLOW` receipt fails re-verification if the resource evidence changes;
- an `ALLOW` receipt fails re-verification if principal identity is altered;
- receipt IDs cannot be copied onto a modified decision body;
- exact resource digests are recomputed rather than trusted.

# Governance binding

Governance evaluates policy internally. The caller cannot bypass policy by omitting a decision.

Current receipts:

```text
REQUEST_POLICY_RECEIPT=<deterministic policy receipt>
APPROVAL_POLICY_RECEIPT=<deterministic policy receipt>
POLICY_DECISIONS_VERIFIED=2
```

Both receipt IDs are stored in their corresponding audit events. The approval receipt also binds the request-policy receipt ID.

Current result:

```text
APPROVAL_RECEIPT_ID=approval-337eabbe4239
AUDIT_HEAD=72a7df85a465765b7794ef521c6aefd6d64885deaf7086462615c4e34abb7928
```

# Dual-verifier proof

Python:

```text
POLICY_VERIFIED=true
IDENTITY_VERIFIED=true
AUDIT_VERIFIED=true
EVIDENCE_ROOM_VERIFIED=true
```

Node:

```text
policy_verified=true
identity_verified=true
audit_verified=true
NODE_EVIDENCE_ROOM_VERIFIED=true
```

Both verifiers independently recompute:

- policy receipt hashes;
- exact request-resource digest;
- exact approval-resource digest;
- principal/session binding;
- tenant binding;
- operation binding;
- audit-event receipt binding.

# Product integration

The Action Contract panel displays:

```text
IDENTITIES · 2 VERIFIED
POLICY · 2 ALLOW RECEIPTS
AUDIT CHAIN · 2 EVENTS · VERIFIED
EXTERNAL EXECUTION · FALSE
```

# Full gate

```text
49 passed
POLICY_VERIFIED=true
POLICY_DECISIONS_VERIFIED=2
IDENTITY_VERIFIED=true
AUDIT_VERIFIED=true
DUAL_CONTROL_VERIFIED=true
SHADOW_ONLY=true
HAS_POLICY_RECEIPTS=true
EAGLE_EYE_ZENITH_CHECK_PASS
```

# Explicit limitations

- This is an in-process policy decision point, not an independently deployed policy service.
- Policy version 1.0 intentionally authorizes fixture-only governance and denies live execution.
- There is no production policy administration plane, staged policy rollout, or emergency policy revocation.
- Resource scope currently covers Action Contract governance, not every graph entity or API route.
- Production should separate policy decision, policy administration, policy information, and policy enforcement points; sign policy bundles; test policy changes against sealed authorization cases; and preserve deny receipts in an immutable audit store.
