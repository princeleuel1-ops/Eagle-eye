# CUSTODY ACTIVATION RUNBOOK — the V11 key ceremony

The custody/identity spine is READY: state machine, round-trip protocol,
and signing interlock are sealed. Production VERIFIED is reachable only
through YOUR cloud credentials — the repository cannot fake a remote
signature.

## KMS/HSM (choose aws-kms | gcp-kms | hsm)
1. Provision an asymmetric signing key (Ed25519 or provider-supported) in
   YOUR account; grant sign+get-public-key to the pilot's service identity
   (least privilege; no key export).
2. Write the custody descriptor {provider_class, credentials_ref} into the
   deployment. State becomes CONFIGURED_UNVERIFIED — nothing trusted yet.
3. Run the round-trip: `run_roundtrip_verification(provider, provider_class=…,
   operator=<you>)` — a fresh nonce is signed REMOTELY and verified LOCALLY
   against the provider's fetched public key. verdict=true ⇒ VERIFIED
   (proof is content-hashed; expires after 1h — re-verify on schedule).
4. Production receipts now sign ONLY through `require_production_custody`:
   VERIFIED ∧ production class. Local providers stay refused BY CLASS.

## OIDC identity
1. Register the relying party at YOUR IdP (issuer URL, audience, JWKS).
2. Configure {issuer_url, audience, jwks_source} ⇒ CONFIGURED_UNVERIFIED.
3. Run the identity round-trip (mint at IdP → verify at the relying party:
   issuer+kid pinning, audience, tenant, expiry). verdict=true ⇒ VERIFIED.

## Abort switch
Remove credentials/config, or let the proof expire ⇒ the ladder falls back
fail-closed (DISABLED / CONFIGURED_UNVERIFIED). A failed round-trip parks at
VERIFICATION_FAILED — investigate before retrying.

## What this does NOT grant
Not live data (V10's ceremony) · not external execution (V12) · not external
validation. Until this ceremony runs with real cloud credentials, production
custody remains NOT ESTABLISHED — the rehearsal proves the machine, not the
custody.
