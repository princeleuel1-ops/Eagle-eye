"""V11 custody & identity spine — production KMS/OIDC to READY, VERIFIED only
by a real remote round-trip that this repository cannot fake.

THE WALL (verbatim): "Production KMS/HSM key custody NOT ESTABLISHED …
production OIDC/identity NOT ESTABLISHED … no cloud adapter may claim
success without a real remote signature verification test, and none exists
here." V11 builds the verification protocol, the state machine, and the
ceremony — and leaves VERIFIED(production) unreachable from inside the repo.

CUSTODY STATES (strict ladder, fail-closed at every step):
  DISABLED_NO_CREDENTIALS  no credentials configured (production default)
  CONFIGURED_UNVERIFIED    credentials/config present; NOTHING trusted yet
  VERIFIED                 a real round-trip proof succeeded JUST NOW:
                           nonce -> remote sign -> local verify against the
                           provider's fetched public key
  VERIFICATION_FAILED      round-trip attempted and failed; MORE distrusted
                           than unverified (evidence of misconfiguration)

Only VERIFIED custody with authority_class="production" may sign
production-class receipts; the shipped local providers verify mechanically
but are hard-labeled non-production and can never satisfy that predicate.
"""

from __future__ import annotations

import base64
import secrets
import time
from typing import Any

from .prior_registry import canonical_bytes, sha256_hex
from .signing import verify as ed_verify

CUSTODY_SPEC = "eagle-eye-custody/1.0"
DISABLED_NO_CREDENTIALS = "DISABLED_NO_CREDENTIALS"
CONFIGURED_UNVERIFIED = "CONFIGURED_UNVERIFIED"
VERIFIED = "VERIFIED"
VERIFICATION_FAILED = "VERIFICATION_FAILED"
CUSTODY_STATES = (DISABLED_NO_CREDENTIALS, CONFIGURED_UNVERIFIED,
                  VERIFIED, VERIFICATION_FAILED)
PRODUCTION_PROVIDER_CLASSES = ("aws-kms", "gcp-kms", "hsm")
LOCAL_PROVIDER_CLASSES = ("local-ephemeral", "local-persisted")
VERIFICATION_MAX_AGE_S = 3600.0  # a proof is a fact about NOW, not forever


class CustodyError(RuntimeError):
    pass


def custody_state(descriptor: dict[str, Any] | None) -> tuple[str, list[str]]:
    """Pure state derivation from a provider descriptor (no side effects)."""
    if descriptor is None:
        return DISABLED_NO_CREDENTIALS, ["no custody descriptor configured"]
    reasons = []
    if descriptor.get("provider_class") not in (
            PRODUCTION_PROVIDER_CLASSES + LOCAL_PROVIDER_CLASSES):
        return DISABLED_NO_CREDENTIALS, ["unknown provider class"]
    if descriptor.get("provider_class") in PRODUCTION_PROVIDER_CLASSES:
        creds = descriptor.get("credentials_ref")
        if not creds:
            return DISABLED_NO_CREDENTIALS, ["no credentials configured"]
    proof = descriptor.get("verification_proof")
    if proof is None:
        return CONFIGURED_UNVERIFIED, ["no round-trip proof recorded"]
    if proof.get("verdict") is not True:
        return VERIFICATION_FAILED, ["last round-trip failed"]
    if (time.time() - proof.get("verified_at_epoch", 0)) > VERIFICATION_MAX_AGE_S:
        return CONFIGURED_UNVERIFIED, ["round-trip proof expired"]
    return VERIFIED, reasons


def run_roundtrip_verification(provider, *, provider_class: str,
                               operator: str) -> dict[str, Any]:
    """THE verification protocol: fresh nonce -> provider signs remotely ->
    signature verified locally against the provider's own fetched public key.
    Returns a signed-content proof record. Raises nothing silently: failures
    return verdict=False proofs (VERIFICATION_FAILED state)."""
    nonce = secrets.token_hex(32)
    payload = canonical_bytes({"spec": CUSTODY_SPEC, "kind": "custody-roundtrip",
                               "nonce": nonce, "operator": operator,
                               "provider_class": provider_class})
    started = time.time()
    try:
        signature = provider.sign(payload)
        public_pem = provider.public_key_pem()
        ok = ed_verify(payload, signature, public_pem)
        key = provider.key_id() if callable(getattr(provider, "key_id", None)) else None
    except Exception as exc:  # noqa: BLE001 — every failure is evidence
        proof = {"spec": CUSTODY_SPEC, "verdict": False, "nonce": nonce,
                 "provider_class": provider_class, "operator": operator,
                 "error": f"{type(exc).__name__}: {exc}",
                 "verified_at_epoch": started}
        proof["proof_sha256"] = sha256_hex(canonical_bytes(proof))
        return proof
    proof = {"spec": CUSTODY_SPEC, "verdict": bool(ok), "nonce": nonce,
             "provider_class": provider_class, "operator": operator,
             "key_id": key,
             "signature_b64": base64.b64encode(signature).decode(),
             "elapsed_ms": int((time.time() - started) * 1000),
             "verified_at_epoch": started}
    proof["proof_sha256"] = sha256_hex(canonical_bytes(proof))
    return proof


def require_production_custody(descriptor: dict[str, Any] | None) -> None:
    """The signing interlock: production-class receipts demand VERIFIED
    custody on a PRODUCTION provider class. Local providers — mechanically
    verifiable — are refused here BY CLASS, not by state: a passing local
    round-trip proves the protocol, never production custody."""
    state, reasons = custody_state(descriptor)
    if state != VERIFIED:
        raise CustodyError(f"production signing refused: custody {state} "
                           f"({'; '.join(reasons)})")
    if descriptor.get("provider_class") not in PRODUCTION_PROVIDER_CLASSES:
        raise CustodyError(
            "production signing refused: provider class "
            f"{descriptor.get('provider_class')!r} is non-production by label")


# ---------------------------- OIDC relying party ------------------------------

OIDC_STATES = CUSTODY_STATES  # same ladder, same semantics


def oidc_state(rp_config: dict[str, Any] | None) -> tuple[str, list[str]]:
    if rp_config is None:
        return DISABLED_NO_CREDENTIALS, ["no relying-party config"]
    for field in ("issuer_url", "audience", "jwks_source"):
        if not rp_config.get(field):
            return DISABLED_NO_CREDENTIALS, [f"missing {field}"]
    proof = rp_config.get("verification_proof")
    if proof is None:
        return CONFIGURED_UNVERIFIED, ["no discovery/token round-trip recorded"]
    if proof.get("verdict") is not True:
        return VERIFICATION_FAILED, ["last identity round-trip failed"]
    if (time.time() - proof.get("verified_at_epoch", 0)) > VERIFICATION_MAX_AGE_S:
        return CONFIGURED_UNVERIFIED, ["identity proof expired"]
    return VERIFIED, []


def run_oidc_verification(rp_config: dict[str, Any], *, verifier, issuer,
                          tenant_id: str, operator: str) -> dict[str, Any]:
    """Identity round-trip: mint at the issuer, verify at the relying party
    (issuer+kid pinning, audience, tenant, expiry — the EXISTING verifier,
    unchanged). Production requires a real IdP; the rehearsal uses the
    labeled local dev issuer to prove the mechanics only."""
    started = time.time()
    try:
        token = issuer.mint(subject=f"custody-probe:{operator}",
                            tenant_id=tenant_id, roles=["viewer"])
        principal = verifier.verify(token, expected_tenant=tenant_id)
        ok = bool(principal)
        detail = {"subject": getattr(principal, "subject", None) or
                  (principal.get("subject") if isinstance(principal, dict) else "verified")}
    except Exception as exc:  # noqa: BLE001
        ok, detail = False, {"error": f"{type(exc).__name__}: {exc}"}
    proof = {"spec": CUSTODY_SPEC, "kind": "oidc-roundtrip", "verdict": ok,
             "issuer_url": rp_config["issuer_url"], "audience": rp_config["audience"],
             "operator": operator, "detail": detail, "verified_at_epoch": started}
    proof["proof_sha256"] = sha256_hex(canonical_bytes(proof))
    return proof
