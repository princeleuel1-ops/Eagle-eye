# V11 — CUSTODY & IDENTITY SPINE
Base: V10 tree 6a88c83e (31 gates / 413 tests). Additive.

## The wall, verbatim
"Production KMS/HSM key custody NOT ESTABLISHED … production OIDC/identity
NOT ESTABLISHED … no cloud adapter may claim success without a real remote
signature verification test, and none exists here."

## The instrument (src/eagle_eye/custody.py)
- Strict state ladder: DISABLED_NO_CREDENTIALS → CONFIGURED_UNVERIFIED →
  VERIFIED / VERIFICATION_FAILED. Configuration is never trust; a failed
  round-trip is MORE distrusted than no attempt; proofs expire (1h).
- THE round-trip protocol: fresh nonce → REMOTE sign → LOCAL verify against
  the provider's fetched public key → content-hashed proof record.
- The signing interlock `require_production_custody`: production receipts
  demand VERIFIED ∧ production provider class. Local providers (which verify
  mechanically) are refused BY CLASS — a passing local round-trip proves the
  protocol, never production custody.
- OIDC relying-party ladder with the same semantics, verified through the
  EXISTING IdentityVerifier (issuer+kid pinning, audience, tenant, expiry).

## The gate (required gate 32: custody-rehearsal)
11 stages, sealed green: defaults disabled; configured≠trusted; local
round-trip reaches VERIFIED mechanically; broken provider →
VERIFICATION_FAILED; stale proof downgrades; production signing refused for
all five non-qualifying descriptors INCLUDING fully-VERIFIED local (by
class); tampered proof detected by content hash; OIDC ladder mirrors.
PRODUCTION_CUSTODY_REACHABLE=false by construction.

## Honest boundary
The spine is READY; production custody/identity remain NOT ESTABLISHED until
the operator's ceremony (CUSTODY_ACTIVATION_RUNBOOK.md) runs with real cloud
credentials and a real IdP. No cloud call ships here. EXTERNALLY VALIDATED:
nothing. external_action=false.
