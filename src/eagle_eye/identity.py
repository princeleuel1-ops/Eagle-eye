from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from .signing import key_id, sign, verify


class IdentityError(ValueError):
    """Raised when an identity assertion cannot be trusted."""


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _b64decode(value: str, *, field: str) -> bytes:
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise IdentityError(f"{field} encoding is invalid") from exc
    if _b64encode(decoded) != value:
        raise IdentityError(f"{field} encoding is invalid")
    return decoded


def _json_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def issue_assertion(claims: dict[str, Any], *, private_key: bytes, public_key: bytes) -> str:
    header = {"alg": "EdDSA", "typ": "EE-SESSION", "kid": key_id(public_key)}
    encoded_header = _b64encode(_json_bytes(header))
    encoded_claims = _b64encode(_json_bytes(claims))
    signing_input = f"{encoded_header}.{encoded_claims}".encode()
    signature = _b64encode(sign(signing_input, private_key))
    return f"{encoded_header}.{encoded_claims}.{signature}"


def verify_assertion(
    token: str,
    *,
    registry: dict[str, Any],
    expected_audience: str,
    expected_tenant: str,
    now: int,
    revoked_jtis: set[str],
) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise IdentityError("assertion format is invalid")
    try:
        header = json.loads(_b64decode(parts[0], field="header"))
        claims = json.loads(_b64decode(parts[1], field="claims"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise IdentityError("assertion JSON is invalid") from exc
    signature = _b64decode(parts[2], field="signature")
    if header.get("alg") != "EdDSA" or header.get("typ") != "EE-SESSION":
        raise IdentityError("assertion algorithm or type is invalid")
    issuer = next(
        (
            item
            for item in registry.get("trusted_issuers", [])
            if item.get("issuer") == claims.get("iss") and item.get("key_id") == header.get("kid")
        ),
        None,
    )
    if issuer is None:
        raise IdentityError("trusted issuer not found")
    public_key = issuer.get("public_key_pem", "").encode()
    if key_id(public_key) != header["kid"]:
        raise IdentityError("trusted issuer key fingerprint is invalid")
    if not verify(f"{parts[0]}.{parts[1]}".encode(), signature, public_key):
        raise IdentityError("assertion signature is invalid")
    required = {"iss", "aud", "sub", "tenant_id", "roles", "iat", "exp", "jti"}
    if required - claims.keys():
        raise IdentityError("required identity claims are missing")
    if not all(isinstance(claims[name], str) and claims[name] for name in ("iss", "aud", "sub", "tenant_id", "jti")):
        raise IdentityError("identity string claims are invalid")
    if not isinstance(claims["iat"], int) or isinstance(claims["iat"], bool) or not isinstance(claims["exp"], int) or isinstance(claims["exp"], bool):
        raise IdentityError("identity timestamps are invalid")
    if not isinstance(claims["roles"], list) or not claims["roles"] or not all(isinstance(role, str) and role for role in claims["roles"]):
        raise IdentityError("identity roles are invalid")
    if claims["aud"] != expected_audience or claims["aud"] not in issuer.get("audiences", []):
        raise IdentityError("assertion audience is invalid")
    if claims["tenant_id"] != expected_tenant or claims["tenant_id"] not in issuer.get("allowed_tenants", []):
        raise IdentityError("assertion tenant is invalid")
    if claims["exp"] <= now:
        raise IdentityError("assertion expired")
    # V6 (additive): not-before enforcement. Assertions without nbf keep the
    # exact V5 behavior; a present nbf must be an integer and must have
    # arrived (small forward skew tolerated, mirroring the iat rule).
    if "nbf" in claims:
        if not isinstance(claims["nbf"], int) or isinstance(claims["nbf"], bool):
            raise IdentityError("assertion not-before timestamp is invalid")
        if claims["nbf"] > now + 60:
            raise IdentityError("assertion is not yet valid (nbf in the future)")
    if claims["iat"] > now + 60:
        raise IdentityError("assertion issued-at time is in the future")
    if claims["exp"] <= claims["iat"] or claims["exp"] - claims["iat"] > issuer.get("max_ttl_seconds", 0):
        raise IdentityError("assertion lifetime exceeds issuer policy")
    if claims["jti"] in revoked_jtis:
        raise IdentityError("assertion session is revoked")
    return {
        "id": claims["sub"],
        "tenant_id": claims["tenant_id"],
        "roles": sorted(set(claims["roles"])),
        "session_id": claims["jti"],
        "issuer": claims["iss"],
    }
