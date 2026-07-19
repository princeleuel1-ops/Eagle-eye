"""Dependency and version provenance (V4 blocker 4).

One rule: `dependency_lock_sha256` is the SHA-256 of the committed lock file
`environment/requirements-lock.txt` and MUST exist — a missing lock raises
instead of degrading to "NOT_AVAILABLE". A companion verifier proves the
RUNNING interpreter actually satisfies the audited pin set, so the digest is
a claim about this process, not just about a file.
"""

from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path
from typing import Any

from .prior_registry import sha256_hex

LOCK_RELPATH = "environment/requirements-lock.txt"


def lock_path(root: Path) -> Path:
    return root / LOCK_RELPATH


def dependency_lock_digest(root: Path) -> str:
    """SHA-256 of the audited lock file. Fail-closed: never NOT_AVAILABLE."""
    path = lock_path(root)
    if not path.exists():
        raise FileNotFoundError(
            f"dependency lock missing at {path}; provenance is mandatory (V4 blocker 4) — "
            "run `make lock` or restore environment/requirements-lock.txt")
    return sha256_hex(path.read_bytes())


def parse_lock(root: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in lock_path(root).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^([A-Za-z0-9_.\-]+)==(\S+)$", line)
        if not match:
            raise ValueError(f"non-pinned lock line refused (exact pins only): {line!r}")
        pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    return pins


def verify_dependency_lock(root: Path) -> dict[str, Any]:
    """Compare the RUNNING environment against the audited lock pins."""
    pins = parse_lock(root)
    rows = []
    for name, pinned in sorted(pins.items()):
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            installed = None
        rows.append({"package": name, "pinned": pinned, "installed": installed,
                     "match": installed == pinned})
    return {
        "lock_sha256": dependency_lock_digest(root),
        "packages": rows,
        "all_match": all(r["match"] for r in rows),
    }
