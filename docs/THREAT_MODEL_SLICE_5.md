# Eagle Eye Zenith Slice 5 Threat Model

## Scope

Local fixture evidence export, signer verification, tenant binding, local HTTP command surface, and evidence-derived browser rendering.

This is not a production authentication design. The server binds to loopback and no externally reachable deployment is authorized by this document.

## Trust boundaries

1. CSV/JSON fixture files entering the ingestion layer.
2. Evidence archive crossing from producer to verifier.
3. Public key embedded in an evidence archive.
4. Trust registry supplied independently to a verifier.
5. Expected tenant supplied independently to a verifier.
6. API JSON crossing into the browser DOM.
7. HTTP requests entering the loopback server.

## Protected assets

- tenant evidence;
- action status and approval history;
- source-to-decision provenance;
- signer identity;
- benchmark receipts;
- operator trust;
- future customer data.

## STRIDE findings

| Threat | Current control | Remaining limitation |
|---|---|---|
| Spoofing | Ed25519 signature, computed signer key ID, external trust-registry match | Fixture registry is generated locally, not production KMS/IAM |
| Tampering | SHA-256 file binding, signed canonical manifest, dual verification | Archive confidentiality is not provided |
| Repudiation | Signed run ID, tenant ID, signer ID, mutation receipts | No production append-only audit store |
| Information disclosure | Loopback bind, no secrets, no external deployment, restrictive headers | No encryption-at-rest or production tenant store yet |
| Denial of service | Small fixture inputs, local-only scope | No production size caps, rate limiting, or queue isolation yet |
| Elevation of privilege | No external action endpoint; approval disabled; tenant expected independently | No production RBAC/session system yet |

## Abuse cases tested

1. Cryptographically valid archive signed by an unknown key → rejected.
2. Trusted tenant-A archive presented as tenant B → rejected.
3. Signed archive content changed without re-signing → rejected by Python and Node.
4. Development/holdout contamination → benchmark rejected.
5. Evidence-derived strings containing markup → encoded before browser insertion.

## Browser controls

- strict same-origin CSP;
- frame denial;
- MIME sniffing disabled;
- no-referrer policy;
- camera, microphone, and geolocation disabled;
- request correlation ID on every response;
- structured JSON HTTP logs;
- no auth tokens or request bodies logged.

## Explicit non-claims

- No production identity provider.
- No production KMS.
- No production tenant database.
- No RBAC.
- No public-network hardening.
- No confidential archive encryption.
- No external action execution.
