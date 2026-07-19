# V11 CLAIM LEDGER — Custody & Identity (delta over V10)

| Area | Claim | Class | Evidence |
|---|---|---|---|
| State ladder | absence/unknown/credential-less ⇒ DISABLED; config ⇒ CONFIGURED_UNVERIFIED (never trusted); failure ⇒ VERIFICATION_FAILED; proofs expire | MECHANICALLY VERIFIED | tests/test_custody.py; gate stages 1-3,5-6 |
| Round-trip protocol | nonce → remote sign → local verify vs fetched key; content-hashed proof; failures recorded as evidence | MECHANICALLY VERIFIED (local providers) | test_roundtrip_reaches_verified…; gate stage 4 |
| Production interlock | production signing demands VERIFIED ∧ production class; VERIFIED local refused BY CLASS | MECHANICALLY VERIFIED | test_production_interlock…; gate production_signing_refused_all_five |
| Proof integrity | any field mutation breaks the content hash | MECHANICALLY VERIFIED | gate tampered_proof_hash_mismatch |
| OIDC ladder | same semantics; round-trip through the UNCHANGED IdentityVerifier on the labeled dev issuer | MECHANICALLY VERIFIED (mechanics only) | test_oidc_ladder…; gate stages 9-11 |

## Boundary
Production KMS/HSM custody and production OIDC identity: **NOT ESTABLISHED**
— reachable only via the operator ceremony with real credentials. No cloud
adapter ships a success path without a real remote signature. EXTERNALLY
VALIDATED: nothing. external_action=false.
