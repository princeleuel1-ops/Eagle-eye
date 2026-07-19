---
type: verification_receipt
title: Eagle Eye Zenith Slice 8 — Trusted Short-Lived Identity Assertions
timestamp: 2026-07-12
---

# Executable claim

The governance requester and approver are no longer accepted as caller-supplied principal dictionaries. Each principal is derived from a short-lived Ed25519-signed identity assertion validated against a trusted issuer registry, then bound by session ID into the signed governance audit chain.

# Assertion contract

Header:

- algorithm: `EdDSA`;
- type: `EE-SESSION`;
- issuer key ID: SHA-256 fingerprint of Ed25519 SPKI.

Claims:

- issuer;
- audience;
- subject;
- tenant ID;
- roles;
- issued-at time;
- expiration time;
- unique session ID.

# Verification gates

An assertion is accepted only when:

1. its compact encoding is canonical;
2. its algorithm and type are exact;
3. issuer and key ID exist in the independently supplied issuer registry;
4. the registry public key fingerprint matches the key ID;
5. the Ed25519 signature verifies;
6. every required claim is present and correctly typed;
7. audience matches both server expectation and issuer policy;
8. tenant matches both server expectation and issuer policy;
9. expiration is later than verification time;
10. issued-at is not unreasonably in the future;
11. expiration is later than issued-at;
12. lifetime does not exceed issuer policy;
13. session ID is not revoked;
14. roles are a non-empty string list.

# Positive proof

```text
IDENTITY_ASSERTIONS_VERIFIED=2
IDENTITY_PRINCIPALS_VERIFIED=2
IDENTITY_VERIFIED=true
```

Verified identities:

- `fixture-analyst` with `analyst` role;
- `fixture-approver` with `approver` role.

Both are scoped to `tenant-demo` and audience `eagle-eye-zenith`.

# Adversarial proofs

Tests reject:

- forged assertion signatures;
- non-canonical signature encodings;
- expired assertions;
- lifetimes exceeding issuer policy;
- wrong audiences;
- wrong tenants;
- revoked session IDs;
- untrusted issuer keys;
- missing or malformed claims;
- future issued-at timestamps beyond allowed skew.

# Governance binding

The governance request is created from the verified analyst principal. The approval is created from the independently verified approver principal. Their session IDs are written into their corresponding audit events.

The governance runner checks:

- exactly two identity receipts were verified;
- request session matches the first audit event;
- approver session matches the second audit event;
- approval receipt matches the terminal audit event;
- governance tenant matches the audit commitment tenant.

Current chain:

```text
AUDIT_EVENTS=2
AUDIT_HEAD=6eae62b29d4e35be9a1313e3f7134cb075fe23bc52b87d3f62605a192734186f
AUDIT_VERIFIED=true
```

# Dual-verifier proof

Python:

```text
IDENTITY_VERIFIED=true
AUDIT_VERIFIED=true
EVIDENCE_ROOM_VERIFIED=true
```

Node:

```text
identity_verified=true
audit_verified=true
NODE_EVIDENCE_ROOM_VERIFIED=true
```

Both verifiers independently validate assertion signatures, issuer keys, audiences, tenants, lifetimes, subjects, session IDs, assertion digests, audit links, and the outer evidence signature.

# Product integration

The Action Contract panel displays:

```text
GOVERNANCE HARNESS · APPROVED_SHADOW
DUAL CONTROL · TRUE
EXTERNAL EXECUTION · FALSE
IDENTITIES · 2 VERIFIED
AUDIT CHAIN · 2 EVENTS · VERIFIED
```

# Full gate

```text
37 passed
IDENTITY_ASSERTIONS_VERIFIED=2
IDENTITY_VERIFIED=true
SIGNER_TRUSTED=true
TENANT_VERIFIED=true
AUDIT_VERIFIED=true
DUAL_CONTROL_VERIFIED=true
SHADOW_ONLY=true
HAS_VERIFIED_IDENTITY=true
EAGLE_EYE_ZENITH_CHECK_PASS
```

# Explicit limitations

- The issuer is an ephemeral fixture identity, not a production IdP.
- Fixture assertions use a fixed historical verification window for deterministic evidence replay.
- No application endpoint accepts these synthetic assertion-evidence strings as credentials.
- There is no login, refresh-token, browser-session, MFA, SCIM, or production revocation service.
- The fixture issuer registry is inside the signed evidence room; production must pin trusted issuer metadata in independently administered deployment configuration.
- Authorization still needs a production policy engine and resource-level scopes beyond the current analyst/approver roles.
