---
type: verification_receipt
title: Eagle Eye Zenith Slice 5 — Trusted Signer and Tenant Boundary
timestamp: 2026-07-12
---

# Executable claim

Python and Node independently reject evidence rooms when the signer is not present in an independently supplied trust registry or when the signed tenant does not match the independently supplied expected tenant.

# Positive proof

```text
TENANT_ID=tenant-demo
SIGNATURE_VERIFIED=true
SIGNER_TRUSTED=true
TENANT_VERIFIED=true
EVIDENCE_ROOM_VERIFIED=true
NODE_EVIDENCE_ROOM_VERIFIED=true
```

The signed manifest includes:

- tenant ID;
- signer key ID;
- archive file hash;
- run ID;
- fixture mode;
- source authority;
- signature state.

The verifier recomputes the Ed25519 SPKI fingerprint and requires all of the following to match:

1. signed manifest key ID;
2. embedded public key fingerprint;
3. trust-registry key ID;
4. trust-registry public key;
5. manifest tenant;
6. signer allowed-tenant list;
7. independently supplied expected tenant.

# Negative proofs

## Unknown signer

A valid archive and signature from signer A are checked against a registry containing signer B.

Observed:

```text
signature_verified=true
signer_trusted=false
verified=false
```

## Cross-tenant replay

A trusted archive signed for `tenant-a` is verified with expected tenant `tenant-b`.

Observed in Python and Node:

```text
signature_verified=true
signer_trusted=true
tenant_verified=false
verified=false
```

## Tampering

Previously verified negative test remains active:

```text
hashes_verified=false
verified=false
```

# Browser hardening

Live response verification confirmed:

```text
X-Request-ID=<unique ID>
Content-Security-Policy=default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'
X-Frame-Options=DENY
X-Content-Type-Options=nosniff
Referrer-Policy=no-referrer
Permissions-Policy=camera=(), microphone=(), geolocation=()
```

Evidence-derived entity values, JSON, trace IDs, and unknown descriptions are HTML-encoded before insertion. Inline style mutation was replaced with a CSP-compatible CSS class.

Browser verification after strict CSP:

```text
console_messages=0
javascript_errors=0
```

# Full gate

```text
19 passed
SIGNATURE_VERIFIED=true
SIGNER_TRUSTED=true
TENANT_VERIFIED=true
NODE_EVIDENCE_ROOM_VERIFIED=true
CONTAMINATION_DETECTED=false
BENEFICIAL_MUTATION_PROMOTED=true
HARMFUL_MUTATION_REJECTED=true
EAGLE_EYE_ZENITH_CHECK_PASS
```

# Brittle point

The fixture runner generates both its ephemeral signing identity and its separate local trust-registry artifact. This proves the verifier contract and cross-tenant enforcement, but an attacker controlling the entire local artifact directory could replace both. Production must anchor the trust registry outside the evidence producer through KMS/IAM, a deployed verifier configuration, or a separately administered signed registry.
