"""Prior Task Registry: canonical schema, as-of boundaries, deterministic releases.

Invariants enforced here (fail closed):
  I1  historical prior tasks and current target evidence remain distinct
  I2  nothing after an as-of cutoff may influence an earlier prediction
  I3  tenant data never cross tenant boundaries
  I4  every load-bearing datum has provenance (sources required)
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA_VERSION = "prior-task/1.0"
REGISTRY_SPEC = "eagle-eye-prior-registry/1.0"

REQUIRED_TASK_FIELDS = (
    "schema_version", "task_id", "tenant_id", "disruption_class",
    "as_of_start", "as_of_end", "entity_refs", "observations",
    "intervention", "realized", "sources", "eligibility",
)


class RegistryError(ValueError):
    """Raised when a task violates the registry data contract."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def task_content_hash(task: dict[str, Any]) -> str:
    return sha256_hex(canonical_bytes(task))


def validate_task(task: dict[str, Any]) -> dict[str, Any]:
    """Validate one prior task against the data contract. Returns the task."""
    missing = [field for field in REQUIRED_TASK_FIELDS if field not in task]
    if missing:
        raise RegistryError(f"task missing required fields: {', '.join(missing)}")
    if task["schema_version"] != SCHEMA_VERSION:
        raise RegistryError(f"unsupported schema_version {task['schema_version']!r}")
    if not str(task["task_id"]):
        raise RegistryError("task_id must be non-empty")
    if task["as_of_start"] > task["as_of_end"]:
        raise RegistryError(f"task {task['task_id']}: as_of_start after as_of_end")
    for obs in task["observations"]:
        if not (task["as_of_start"] <= obs["t"] <= task["as_of_end"]):
            raise RegistryError(
                f"task {task['task_id']}: observation at {obs['t']} outside as-of window "
                f"[{task['as_of_start']}, {task['as_of_end']}] (temporal leakage)"
            )
    if not task["sources"]:
        raise RegistryError(f"task {task['task_id']}: at least one provenance source required")
    if task["eligibility"].get("status") != "closed":
        raise RegistryError(f"task {task['task_id']}: only closed tasks may enter the registry")
    if "log_final_delay" not in task["realized"]:
        raise RegistryError(f"task {task['task_id']}: realized outcome must include log_final_delay")
    return task


def build_registry(tasks: list[dict[str, Any]], *, release: str = "prior-registry/1") -> dict[str, Any]:
    """Validate every task, reject duplicate ids, emit a deterministic release."""
    seen: set[str] = set()
    for task in tasks:
        validate_task(task)
        if task["task_id"] in seen:
            raise RegistryError(f"duplicate task_id {task['task_id']}")
        seen.add(task["task_id"])
    ordered = sorted(tasks, key=lambda t: (t["as_of_end"], t["task_id"]))
    manifest_rows = [{"task_id": t["task_id"], "content_sha256": task_content_hash(t)} for t in ordered]
    registry = {
        "spec": REGISTRY_SPEC,
        "release": release,
        "schema_version": SCHEMA_VERSION,
        "task_count": len(ordered),
        "manifest": manifest_rows,
        "tasks": ordered,
    }
    registry["manifest_sha256"] = sha256_hex(canonical_bytes(manifest_rows))
    registry["registry_release_id"] = f"prreg-{sha256_hex(canonical_bytes({'release': release, 'manifest_sha256': registry['manifest_sha256']}))[:12]}"
    return registry


def verify_registry(registry: dict[str, Any]) -> bool:
    """Recompute manifest and release commitments; True only if intact."""
    rows = [{"task_id": t["task_id"], "content_sha256": task_content_hash(t)} for t in registry["tasks"]]
    if rows != registry["manifest"]:
        return False
    if sha256_hex(canonical_bytes(rows)) != registry["manifest_sha256"]:
        return False
    expected_release = f"prreg-{sha256_hex(canonical_bytes({'release': registry['release'], 'manifest_sha256': registry['manifest_sha256']}))[:12]}"
    return expected_release == registry["registry_release_id"]


def tasks_visible_at(
    registry: dict[str, Any],
    *,
    tenant_id: str,
    as_of_cutoff: str,
) -> dict[str, Any]:
    """Apply the hard eligibility boundaries (tenant + as-of). Fail closed.

    Returns visible tasks plus an exclusion receipt naming every rejected task
    and the boundary that rejected it. The exclusion receipt is part of the
    evidence chain: a verifier can recompute it from the registry alone.
    """
    visible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for task in registry["tasks"]:
        if task["tenant_id"] != tenant_id:
            excluded.append({"task_id": task["task_id"], "reason": "tenant_boundary"})
            continue
        if task["as_of_end"] > as_of_cutoff:
            excluded.append({"task_id": task["task_id"], "reason": "not_closed_before_cutoff"})
            continue
        visible.append(task)
    receipt = {
        "tenant_id": tenant_id,
        "as_of_cutoff": as_of_cutoff,
        "visible_count": len(visible),
        "excluded": excluded,
    }
    receipt["receipt_sha256"] = sha256_hex(canonical_bytes(receipt))
    return {"visible": visible, "exclusion_receipt": receipt}
