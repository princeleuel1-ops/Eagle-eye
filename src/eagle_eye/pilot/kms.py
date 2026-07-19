"""KMS / signing seam — production-shaped key-provider interface.

The interface every signer in the pilot spine consumes:
    sign, verify, key_id, public_key_pem, rotate, state, health

Providers shipped here:
  - EphemeralKeyProvider: in-memory Ed25519 dev keys (labeled NON-PRODUCTION)
  - PersistedKeyProvider: local encrypted-at-rest keys (scrypt-derived key
    from an operator passphrase env var; DISABLED without the passphrase)
  - AwsKmsConfig / GcpKmsConfig: configuration SHAPES that FAIL CLOSED
    without real credentials. No cloud adapter may claim success without a
    real remote signature verification test — none exists here, so their
    state is permanently DISABLED_NO_CREDENTIALS in this environment.

CLAIM DISCIPLINE: production KMS remains NOT ESTABLISHED. A configured
interface is not deployed infrastructure.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ..signing import generate_demo_keypair, key_id as _pem_key_id, sign as _sign, verify as _verify

KMS_SPEC = "eagle-eye-pilot-kms/6.0"
PROVIDER_STATES = ("ACTIVE", "DISABLED", "DISABLED_NO_CREDENTIALS", "ROTATED_OUT")


class KeyProviderError(RuntimeError):
    """Raised on refused signing operations (fail closed)."""


@runtime_checkable
class KeyProvider(Protocol):
    def sign(self, payload: bytes) -> bytes: ...
    def verify(self, payload: bytes, signature: bytes, *, key_id: str | None = None) -> bool: ...
    def key_id(self) -> str: ...
    def public_key_pem(self, *, key_id: str | None = None) -> bytes: ...
    def rotate(self) -> str: ...
    def state(self) -> str: ...
    def health(self) -> dict[str, Any]: ...


class EphemeralKeyProvider:
    """In-memory Ed25519 provider for local development and tests.
    STRICTLY NON-PRODUCTION: keys evaporate with the process; there is no
    custody story here and none is claimed. Supports rotation with old-key
    verification retained (rotated keys can verify, never sign)."""

    PRODUCTION = False
    LABEL = "ephemeral-dev-provider:NOT-PRODUCTION"

    def __init__(self):
        private, public = generate_demo_keypair()
        self._active_kid = _pem_key_id(public)
        self._keys: dict[str, dict[str, Any]] = {
            self._active_kid: {"private": private, "public": public,
                               "state": "ACTIVE", "created_at": time.time()}}

    def sign(self, payload: bytes) -> bytes:
        entry = self._keys[self._active_kid]
        if entry["state"] != "ACTIVE":
            raise KeyProviderError("active key is not in ACTIVE state")
        return _sign(payload, entry["private"])

    def verify(self, payload: bytes, signature: bytes, *,
               key_id: str | None = None) -> bool:
        kid = key_id or self._active_kid
        entry = self._keys.get(kid)
        if entry is None:
            return False
        return _verify(payload, signature, entry["public"])

    def key_id(self) -> str:
        return self._active_kid

    def public_key_pem(self, *, key_id: str | None = None) -> bytes:
        kid = key_id or self._active_kid
        if kid not in self._keys:
            raise KeyProviderError(f"unknown key id {kid!r}")
        return self._keys[kid]["public"]

    def rotate(self) -> str:
        """Mint a new active key; the previous key becomes ROTATED_OUT —
        still able to VERIFY historical signatures, never able to sign."""
        self._keys[self._active_kid]["state"] = "ROTATED_OUT"
        private, public = generate_demo_keypair()
        self._active_kid = _pem_key_id(public)
        self._keys[self._active_kid] = {"private": private, "public": public,
                                        "state": "ACTIVE", "created_at": time.time()}
        return self._active_kid

    def state(self) -> str:
        return "ACTIVE"

    def health(self) -> dict[str, Any]:
        return {"provider": self.LABEL, "state": self.state(),
                "production": self.PRODUCTION, "active_key_id": self._active_kid,
                "keys_held": len(self._keys),
                "evidence_class": "MECHANICALLY VERIFIED (local dev signing only)"}


class PersistedKeyProvider:
    """Local persisted test provider, encrypted at rest.

    The private key PEM is XOR-stream-encrypted with a scrypt-derived
    keystream from an operator passphrase (env var), with an integrity tag
    (HMAC-style sha256 over derived-key + ciphertext). Without the
    passphrase env var the provider is DISABLED and every sign() fails
    closed. This is a LOCAL TEST custody model — explicitly not a KMS, not
    an HSM, and not production custody.
    """

    PRODUCTION = False
    LABEL = "persisted-local-test-provider:NOT-PRODUCTION"
    PASSPHRASE_ENV = "EAGLE_EYE_PILOT_KEY_PASSPHRASE"

    def __init__(self, path: str | Path, *, passphrase_env: str | None = None):
        self.path = Path(path)
        self.passphrase_env = passphrase_env or self.PASSPHRASE_ENV
        self._loaded: dict[str, Any] | None = None

    # -- crypto helpers -------------------------------------------------------
    @staticmethod
    def _stream(key: bytes, n: int) -> bytes:
        out = bytearray()
        counter = 0
        while len(out) < n:
            out.extend(hashlib.sha256(key + counter.to_bytes(8, "big")).digest())
            counter += 1
        return bytes(out[:n])

    def _derive(self, salt: bytes) -> bytes:
        passphrase = os.environ.get(self.passphrase_env, "")
        if not passphrase:
            raise KeyProviderError(
                f"persisted key provider DISABLED: {self.passphrase_env} not set "
                "(fail closed; no default bypass)")
        return hashlib.scrypt(passphrase.encode(), salt=salt, n=2**14, r=8, p=1,
                              dklen=32)

    # -- lifecycle -------------------------------------------------------------
    def initialize(self) -> str:
        """Create and persist a fresh encrypted keypair. Refuses to clobber."""
        if self.path.exists():
            raise KeyProviderError("key file already exists; refusing to overwrite")
        private, public = generate_demo_keypair()
        salt = secrets.token_bytes(16)
        derived = self._derive(salt)
        ciphertext = bytes(a ^ b for a, b in
                           zip(private, self._stream(derived, len(private))))
        record = {
            "spec": KMS_SPEC, "label": self.LABEL,
            "kid": _pem_key_id(public),
            "public_pem": public.decode(),
            "salt_b64": base64.b64encode(salt).decode(),
            "ciphertext_b64": base64.b64encode(ciphertext).decode(),
            "tag": hashlib.sha256(derived + ciphertext).hexdigest(),
            "created_at": time.time(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(record, indent=2, sort_keys=True))
        os.chmod(self.path, 0o600)
        return record["kid"]

    def _load(self) -> dict[str, Any]:
        if self._loaded is not None:
            return self._loaded
        if not self.path.exists():
            raise KeyProviderError("persisted key file missing (fail closed)")
        record = json.loads(self.path.read_text())
        salt = base64.b64decode(record["salt_b64"])
        ciphertext = base64.b64decode(record["ciphertext_b64"])
        derived = self._derive(salt)
        if hashlib.sha256(derived + ciphertext).hexdigest() != record["tag"]:
            raise KeyProviderError(
                "persisted key integrity tag mismatch — wrong passphrase or "
                "corrupted key file (fail closed)")
        private = bytes(a ^ b for a, b in
                        zip(ciphertext, self._stream(derived, len(ciphertext))))
        self._loaded = {"private": private,
                        "public": record["public_pem"].encode(),
                        "kid": record["kid"]}
        return self._loaded

    # -- KeyProvider interface ---------------------------------------------------
    def sign(self, payload: bytes) -> bytes:
        return _sign(payload, self._load()["private"])

    def verify(self, payload: bytes, signature: bytes, *,
               key_id: str | None = None) -> bool:
        record = self._load()
        if key_id and key_id != record["kid"]:
            return False
        return _verify(payload, signature, record["public"])

    def key_id(self) -> str:
        return self._load()["kid"]

    def public_key_pem(self, *, key_id: str | None = None) -> bytes:
        return self._load()["public"]

    def rotate(self) -> str:
        raise KeyProviderError(
            "persisted test provider does not rotate in place; initialize a new "
            "key file and re-pin verifiers (documented operator procedure)")

    def state(self) -> str:
        try:
            self._load()
            return "ACTIVE"
        except KeyProviderError:
            return "DISABLED"

    def health(self) -> dict[str, Any]:
        state = self.state()
        return {"provider": self.LABEL, "state": state,
                "production": self.PRODUCTION,
                "passphrase_env": self.passphrase_env,
                "evidence_class": "MECHANICALLY VERIFIED (local encrypted-at-rest test custody)"
                                  if state == "ACTIVE" else "NOT ESTABLISHED"}


@dataclass(frozen=True)
class _CloudKmsConfigBase:
    """Shared fail-closed behavior for cloud KMS configuration shapes."""
    key_resource: str = ""
    credential_env_vars: tuple[str, ...] = ()
    PROVIDER_NAME = "cloud-kms"

    def _missing(self) -> list[str]:
        return [v for v in self.credential_env_vars if not os.environ.get(v)]

    def state(self) -> str:
        return "DISABLED_NO_CREDENTIALS"

    def sign(self, payload: bytes) -> bytes:
        raise KeyProviderError(
            f"{self.PROVIDER_NAME}: sign refused — no credentials configured "
            f"(missing: {', '.join(self._missing()) or 'all'}). No cloud adapter "
            "may claim success without a real remote signature verification "
            "test. NOT ESTABLISHED: production KMS.")

    def verify(self, payload: bytes, signature: bytes, *, key_id: str | None = None) -> bool:
        return False  # fail closed: cannot vouch for anything remotely

    def key_id(self) -> str:
        raise KeyProviderError(f"{self.PROVIDER_NAME}: no active key (disabled)")

    def public_key_pem(self, *, key_id: str | None = None) -> bytes:
        raise KeyProviderError(f"{self.PROVIDER_NAME}: no key material (disabled)")

    def rotate(self) -> str:
        raise KeyProviderError(f"{self.PROVIDER_NAME}: rotation refused (disabled)")

    def health(self) -> dict[str, Any]:
        return {"provider": self.PROVIDER_NAME, "state": self.state(),
                "production": False, "key_resource": self.key_resource or None,
                "missing_credentials": self._missing() or list(self.credential_env_vars),
                "evidence_class": "NOT ESTABLISHED"}


@dataclass(frozen=True)
class AwsKmsConfig(_CloudKmsConfigBase):
    """Configuration shape for AWS KMS (asymmetric sign/verify). Fail-closed
    placeholder: signing refuses without real credentials and a real remote
    verification test."""
    key_resource: str = ""  # e.g. arn:aws:kms:REGION:ACCOUNT:key/UUID
    credential_env_vars: tuple[str, ...] = (
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_REGION")
    PROVIDER_NAME = "aws-kms(fail-closed placeholder)"


@dataclass(frozen=True)
class GcpKmsConfig(_CloudKmsConfigBase):
    """Configuration shape for Google Cloud KMS. Fail-closed placeholder."""
    key_resource: str = ""  # e.g. projects/P/locations/L/keyRings/R/cryptoKeys/K/cryptoKeyVersions/1
    credential_env_vars: tuple[str, ...] = ("GOOGLE_APPLICATION_CREDENTIALS",)
    PROVIDER_NAME = "gcp-kms(fail-closed placeholder)"


def kms_status(providers: dict[str, Any] | None = None) -> dict[str, Any]:
    """Machine-readable custody statement for receipts and the cockpit."""
    providers = providers or {
        "ephemeral_dev": EphemeralKeyProvider(),
        "aws_kms": AwsKmsConfig(),
        "gcp_kms": GcpKmsConfig(),
    }
    return {
        "spec": KMS_SPEC,
        "providers": {name: p.health() for name, p in providers.items()},
        "production_kms": "NOT ESTABLISHED",
        "honesty": "local providers are labeled non-production; cloud shapes are "
                   "fail-closed placeholders without credentials and remote "
                   "signature verification",
    }
