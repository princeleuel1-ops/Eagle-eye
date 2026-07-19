"""Object storage abstraction — evidence-room archives and immutable blobs.

The reference backend is a content-addressed local filesystem store: every
object is stored under sha256/<aa>/<hash>, written atomically (temp + rename
+ fsync), verified on read, and immutable (an attempt to overwrite a hash
with different bytes is an integrity failure and is refused). Missing or
corrupted objects FAIL CLOSED with a distinct error.

An S3/MinIO configuration shape is provided and fails closed without real
credentials — a configured interface is not deployed infrastructure.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

OBJECTSTORE_SPEC = "eagle-eye-pilot-objectstore/6.0"


class ObjectStoreError(RuntimeError):
    """Base error for object-store failures."""


class ObjectMissing(ObjectStoreError):
    """The requested object does not exist (fail closed)."""


class ObjectCorrupted(ObjectStoreError):
    """Stored bytes no longer match their content address (fail closed)."""


class ObjectImmutable(ObjectStoreError):
    """An overwrite with different bytes was attempted."""


class BackendUnavailable(ObjectStoreError):
    """A configured remote backend is not actually reachable."""


class FsObjectStore:
    """Content-addressed, verify-on-read, immutable local object store."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, digest: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ObjectStoreError("object digest must be lowercase sha256 hex")
        return self.root / "sha256" / digest[:2] / digest

    def put(self, data: bytes) -> str:
        """Store bytes at their content address. Returns the digest.
        Idempotent for identical bytes; refuses to replace differing bytes."""
        digest = hashlib.sha256(data).hexdigest()
        path = self._path_for(digest)
        if path.exists():
            existing = path.read_bytes()
            if hashlib.sha256(existing).hexdigest() != digest:
                raise ObjectCorrupted(
                    f"existing object {digest[:12]} fails verification — "
                    "refusing to mask corruption with an overwrite")
            return digest
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return digest

    def get(self, digest: str) -> bytes:
        """Read and VERIFY. Missing or corrupted objects fail closed."""
        path = self._path_for(digest)
        if not path.exists():
            raise ObjectMissing(f"object {digest[:12]}… is missing")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ObjectCorrupted(
                f"object {digest[:12]}… fails content verification")
        return data

    def exists(self, digest: str) -> bool:
        return self._path_for(digest).exists()

    def stats(self) -> dict[str, Any]:
        files = [p for p in self.root.rglob("*") if p.is_file()]
        return {"spec": OBJECTSTORE_SPEC, "objects": len(files),
                "bytes": sum(p.stat().st_size for p in files),
                "root": str(self.root)}


@dataclass(frozen=True)
class S3Config:
    """Configuration shape for a real S3/MinIO pilot object store. Fails
    closed without endpoint + credentials; never pretends to be wired."""
    endpoint_env: str = "EAGLE_EYE_PILOT_S3_ENDPOINT"
    access_key_env: str = "EAGLE_EYE_PILOT_S3_ACCESS_KEY"
    secret_key_env: str = "EAGLE_EYE_PILOT_S3_SECRET_KEY"

    def connect(self):
        missing = [v for v in (self.endpoint_env, self.access_key_env,
                               self.secret_key_env) if not os.environ.get(v)]
        if missing:
            raise BackendUnavailable(
                f"S3/MinIO backend disabled: {', '.join(missing)} not set. The "
                "supported local reference backend is FsObjectStore. "
                "NOT ESTABLISHED: production object storage.")
        raise BackendUnavailable(
            "S3/MinIO client not in the audited dependency lock; wire it in a "
            "real pilot and independently verify before any live claim.")
