---
type: verification_receipt
title: Eagle Eye Zenith Slice 10 — Hash-Pinned Canonical Policy Release
timestamp: 2026-07-12
---

# Executable claim

Policy decisions are now bound to the exact canonical policy bundle that produced them. A policy name or semantic version alone is insufficient. The release is identified by a reproducible SHA-256 digest and the digest is embedded in request decisions, approval decisions, governance receipts, audit history, the signed run artifact, and both independent verifier results.

# Canonical policy release

```text
policy_id=eagle-eye-action-governance/1.0
release=2026-07-12.1
bundle_sha256=1a47ce736ef27e60fa3aea3d2abcb96aa4e1eb8b22f492c335502d0dc9f75f1f
```

The release source is:

```text
policies/action-governance-v1.json
```

The file is encoded as canonical sorted-key JSON with no insignificant whitespace. Therefore its raw file digest and independently reconstructed canonical-object digest are identical:

```text
RAW_SHA256=1a47ce736ef27e60fa3aea3d2abcb96aa4e1eb8b22f492c335502d0dc9f75f1f
CANONICAL_SHA256=1a47ce736ef27e60fa3aea3d2abcb96aa4e1eb8b22f492c335502d0dc9f75f1f
BYTES_IDENTICAL=true
```

# Strict schema

The loader requires exactly:

- policy ID;
- release;
- fail-closed default effect;
- allowed execution mode;
- exactly the supported request and approval operations;
- required role;
- required resource state;
- evidence requirement flag;
- separation-of-duties flag.

Unknown top-level keys, missing operations, extra operations, malformed rule keys, non-boolean rule flags, non-DENY default behavior, non-FIXTURE execution mode, or unsupported policy IDs are rejected.

# Hash pinning

The fixture runner pins the expected release digest before evaluating any governance transition. If file bytes differ, loading fails before a decision is created.

Both policy decisions include:

```text
policy_id
policy_release
policy_bundle_sha256
```

The policy decision receipt hash covers those fields, so changing the policy release changes the policy receipt, governance receipt, audit head, run hash, and evidence-room signature.

# Adversarial proofs

Tests prove rejection of:

1. a bundle modified to authorize `LIVE` mode while retaining the pinned expected hash;
2. a downgraded policy ID (`0.9`);
3. an unsupported or malformed schema;
4. a bundle body modified after loading while retaining its original `bundle_sha256`;
5. a policy decision copied to a different bundle release;
6. a decision whose embedded bundle hash does not match the active bundle.

The fourth case is important: verification independently recomputes the canonical object digest. It does not trust the `bundle_sha256` field merely because it is present.

# Active decision receipts

```text
REQUEST_POLICY_RECEIPT=policy-405975e038bb
APPROVAL_POLICY_RECEIPT=policy-ee18d6133041
POLICY_DECISIONS_VERIFIED=2
POLICY_RELEASE=2026-07-12.1
POLICY_BUNDLE_SHA256=1a47ce736ef27e60fa3aea3d2abcb96aa4e1eb8b22f492c335502d0dc9f75f1f
```

Resulting governance and audit commitments:

```text
APPROVAL_RECEIPT_ID=approval-4fd80df76cd1
AUDIT_HEAD=b07b6cecd5707e87153b71ec5cc4c5b0dc3f2daaa6ae76a6389bfdee14baa8f8
```

# Python verification

Python independently verifies:

- canonical policy body hash;
- expected policy ID;
- exact release;
- exact bundle digest in both decisions;
- complete policy receipt hashes;
- exact resource digests;
- policy-to-audit bindings.

```text
POLICY_BUNDLE_VERIFIED=true
POLICY_VERIFIED=true
EVIDENCE_ROOM_VERIFIED=true
```

# Node verification

Node independently reconstructs the canonical policy object and verifies the same fields:

```text
policy_bundle_verified=true
policy_verified=true
NODE_EVIDENCE_ROOM_VERIFIED=true
```

# Cockpit

The Action Contract displays the active release rather than only a generic policy label:

```text
POLICY · 2026-07-12.1 · 2 ALLOW RECEIPTS
```

It remains adjacent to:

```text
EXTERNAL EXECUTION · FALSE
AUDIT CHAIN · 2 EVENTS · VERIFIED
```

# Full gate

```text
54 passed
POLICY_RELEASE=2026-07-12.1
POLICY_BUNDLE_SHA256=1a47ce736ef27e60fa3aea3d2abcb96aa4e1eb8b22f492c335502d0dc9f75f1f
POLICY_BUNDLE_VERIFIED=true
POLICY_VERIFIED=true
IDENTITY_VERIFIED=true
AUDIT_VERIFIED=true
EVIDENCE_ROOM_VERIFIED=true
NODE_EVIDENCE_ROOM_VERIFIED=true
SHADOW_ONLY=true
EAGLE_EYE_ZENITH_CHECK_PASS
```

# Explicit limitations

- The bundle is hash-pinned and protected by the signed evidence room, but it is not yet signed by a dedicated production policy authority.
- There is no policy transparency log, release quorum, rollout channel, expiry, rollback authorization, or emergency revocation mechanism.
- This release remains intentionally fixture-only.
- Production should use a distinct policy-signing key, an append-only release log, dual-control release promotion, sealed authorization regression cases, and policy enforcement at every external side-effect boundary.
