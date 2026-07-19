"""Identity & authorization seam — local dev issuer + fail-closed OIDC shape.

Builds on the verified V5 assertion core (eagle_eye.identity): Ed25519-signed
EE-SESSION assertions with issuer+key pinning, audience pinning, tenant claim
binding, expiration / issued-at / TTL policy, and jti revocation. V6 adds:

  - not-before (nbf) enforcement (mission requirement; additive in core)
  - a LOCAL DEVELOPMENT ISSUER, strictly labeled non-production, that mints
    assertions for pilot fixtures (requester / approver / operator personas)
  - key rotation: the issuer registry supports multiple (issuer, kid) entries;
    rotation adds a new active kid and retires the old one for signing while
    historical verification stays possible until the entry is revoked
  - revocation of issuers (registry removal ⇒ 'trusted issuer not found')
  - a role → permission map used by the pilot service for authorization
  - an OIDC provider interface SHAPE that fails closed without external
    configuration — the production identity provider remains NOT ESTABLISHED

No default bypass mode exists: every pilot API call must present a valid
assertion; there is no "trust me" path to mint one outside an issuer.
"""

from __future__ import annotations

import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from ..identity import IdentityError, issue_assertion, verify_assertion
from ..signing import generate_demo_keypair, key_id as _pem_key_id

IDENTITY_SPEC = "eagle-eye-pilot-identity/6.0"
DEV_ISSUER_NAME = "local-dev-issuer:NOT-PRODUCTION"
PILOT_AUDIENCE = "eagle-eye-pilot-cockpit"

# role → permitted operations (deny-by-default: unlisted ⇒ refused)
PERMISSIONS: dict[str, tuple[str, ...]] = {
    "analyst": ("ingest:read", "decision:read", "action:request", "evidence:read",
                "outcome:record", "replay:run"),
    "approver": ("ingest:read", "decision:read", "action:approve", "evidence:read"),
    "operator": ("ingest:run", "ingest:read", "decision:read", "evidence:read",
                 "evidence:export", "replay:run", "outcome:record"),
    "auditor": ("ingest:read", "decision:read", "evidence:read", "evidence:export",
                "replay:run"),
}


class AuthorizationError(ValueError):
    """Raised when an authenticated principal lacks a required permission."""


def permitted(roles: list[str], operation: str) -> bool:
    return any(operation in PERMISSIONS.get(role, ()) for role in roles)


def require_permission(principal: dict[str, Any], operation: str) -> None:
    if not permitted(principal.get("roles", []), operation):
        raise AuthorizationError(
            f"principal {principal.get('id')!r} lacks permission {operation!r} "
            f"(roles: {', '.join(principal.get('roles', [])) or 'none'})")


class LocalDevIssuer:
    """Development-only assertion issuer. STRICTLY NON-PRODUCTION:
    the issuer name embeds the label, minted assertions carry it, and the
    cockpit surfaces it. Supports key rotation and jti revocation."""

    def __init__(self, *, tenants: list[str], max_ttl_seconds: int = 900):
        self.issuer = DEV_ISSUER_NAME
        self.audiences = [PILOT_AUDIENCE]
        self.allowed_tenants = list(tenants)
        self.max_ttl_seconds = max_ttl_seconds
        self._keys: list[dict[str, Any]] = []
        self._revoked_jtis: set[str] = set()
        self.rotate()  # mint the first active key

    # -- keys -----------------------------------------------------------------
    def rotate(self) -> str:
        """Add a fresh signing key; prior keys stop signing but remain in the
        registry for verification of already-issued assertions."""
        private, public = generate_demo_keypair()
        kid = _pem_key_id(public)
        for entry in self._keys:
            entry["active"] = False
        self._keys.append({"kid": kid, "private": private, "public": public,
                           "active": True, "created_at": time.time()})
        return kid

    def active_kid(self) -> str:
        return next(e["kid"] for e in self._keys if e["active"])

    def registry_entries(self) -> list[dict[str, Any]]:
        """Trust-registry entries for eagle_eye.identity.verify_assertion."""
        return [{
            "issuer": self.issuer,
            "key_id": entry["kid"],
            "public_key_pem": entry["public"].decode(),
            "audiences": self.audiences,
            "allowed_tenants": self.allowed_tenants,
            "max_ttl_seconds": self.max_ttl_seconds,
        } for entry in self._keys]

    # -- minting ----------------------------------------------------------------
    def mint(self, *, subject: str, tenant_id: str, roles: list[str],
             ttl_seconds: int = 600, nbf_offset_seconds: int = 0,
             now: int | None = None) -> str:
        if tenant_id not in self.allowed_tenants:
            raise IdentityError(f"dev issuer does not serve tenant {tenant_id!r}")
        issued_at = int(now if now is not None else time.time())
        claims = {
            "iss": self.issuer,
            "aud": PILOT_AUDIENCE,
            "sub": subject,
            "tenant_id": tenant_id,
            "roles": sorted(set(roles)),
            "iat": issued_at,
            "nbf": issued_at + nbf_offset_seconds,
            "exp": issued_at + min(ttl_seconds, self.max_ttl_seconds),
            "jti": f"dev-{secrets.token_hex(8)}",
            "issuer_label": "NOT-PRODUCTION development issuer",
        }
        active = next(e for e in self._keys if e["active"])
        return issue_assertion(claims, private_key=active["private"],
                               public_key=active["public"])

    # -- revocation ---------------------------------------------------------------
    def revoke_jti(self, jti: str) -> None:
        self._revoked_jtis.add(jti)

    @property
    def revoked_jtis(self) -> set[str]:
        return set(self._revoked_jtis)


class IdentityVerifier:
    """Pilot-side verifier: pins issuer registry + audience + tenant, applies
    the core V5 checks AND V6 not-before enforcement, and produces principals
    whose subject identity lands in every approval and audit receipt."""

    def __init__(self, *, registry_entries: list[dict[str, Any]],
                 expected_audience: str = PILOT_AUDIENCE):
        self.registry = {"trusted_issuers": list(registry_entries)}
        self.expected_audience = expected_audience
        self._revoked_jtis: set[str] = set()

    def revoke_jti(self, jti: str) -> None:
        self._revoked_jtis.add(jti)

    def revoke_issuer(self, issuer: str) -> None:
        """Remove EVERY key of an issuer: subsequent verifications fail with
        'trusted issuer not found' — revoked/unknown issuer rejection."""
        self.registry["trusted_issuers"] = [
            e for e in self.registry["trusted_issuers"] if e["issuer"] != issuer]

    def verify(self, token: str, *, expected_tenant: str,
               now: int | None = None) -> dict[str, Any]:
        moment = int(now if now is not None else time.time())
        principal = verify_assertion(
            token,
            registry=self.registry,
            expected_audience=self.expected_audience,
            expected_tenant=expected_tenant,
            now=moment,
            revoked_jtis=self._revoked_jtis,
        )
        principal["authenticated_at"] = moment
        return principal


@dataclass(frozen=True)
class OidcProviderConfig:
    """Interface SHAPE for an authorized production OIDC provider.

    FAILS CLOSED: without external configuration (issuer URL, client id,
    JWKS) there is nothing to verify against and load() refuses. No secrets
    are committed anywhere in this repository; nothing here dials out.
    The production identity provider remains NOT ESTABLISHED until an
    authorized pilot configures and independently verifies one."""
    issuer_url_env: str = "EAGLE_EYE_PILOT_OIDC_ISSUER"
    client_id_env: str = "EAGLE_EYE_PILOT_OIDC_CLIENT_ID"
    jwks_url_env: str = "EAGLE_EYE_PILOT_OIDC_JWKS_URL"

    def load(self):
        missing = [v for v in (self.issuer_url_env, self.client_id_env,
                               self.jwks_url_env) if not os.environ.get(v)]
        if missing:
            raise IdentityError(
                "OIDC provider disabled: missing configuration "
                f"({', '.join(missing)}). The local development issuer is the "
                "only issuer in this reference environment and it is labeled "
                "NOT-PRODUCTION. NOT ESTABLISHED: production identity.")
        raise IdentityError(
            "OIDC verification requires a JWKS client and remote validation "
            "test that are intentionally NOT stubbed here — wire and verify "
            "them in an authorized pilot (no mock may claim integration).")


def identity_status(issuer: LocalDevIssuer | None = None) -> dict[str, Any]:
    return {
        "spec": IDENTITY_SPEC,
        "development_issuer": {
            "name": DEV_ISSUER_NAME,
            "production": False,
            "active_kid": issuer.active_kid() if issuer else None,
            "keys_in_registry": len(issuer.registry_entries()) if issuer else 0,
        },
        "oidc_provider": {"state": "DISABLED_NOT_CONFIGURED",
                          "evidence_class": "NOT ESTABLISHED"},
        "permission_model": {role: list(ops) for role, ops in PERMISSIONS.items()},
        "no_default_bypass": True,
    }
