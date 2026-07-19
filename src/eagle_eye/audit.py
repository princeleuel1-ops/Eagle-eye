from __future__ import annotations

import hashlib
import json
from typing import Any

GENESIS_HASH = "0" * 64


class AuditError(ValueError):
    """Raised when audit append or verification invariants fail."""


def _hash_event(event: dict[str, Any]) -> str:
    body = {key: value for key, value in event.items() if key != "event_hash"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


class AuditLedger:
    def __init__(self, tenant_id: str) -> None:
        if not tenant_id:
            raise AuditError("tenant is required")
        self.tenant_id = tenant_id
        self.events: list[dict[str, Any]] = []
        self._idempotency_keys: set[str] = set()

    @property
    def head(self) -> str:
        return self.events[-1]["event_hash"] if self.events else GENESIS_HASH

    def append(
        self,
        event_type: str,
        *,
        actor_id: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not event_type or not actor_id or not idempotency_key:
            raise AuditError("event type, actor, and idempotency key are required")
        if idempotency_key in self._idempotency_keys:
            raise AuditError("replay detected for idempotency key")
        event = {
            "sequence": len(self.events) + 1,
            "tenant_id": self.tenant_id,
            "event_type": event_type,
            "actor_id": actor_id,
            "idempotency_key": idempotency_key,
            "previous_hash": self.head,
            "payload": payload,
        }
        event["event_hash"] = _hash_event(event)
        self.events.append(event)
        self._idempotency_keys.add(idempotency_key)
        return event.copy()


def verify_chain(
    events: list[dict[str, Any]],
    *,
    expected_tenant: str,
    expected_head: str,
    expected_length: int,
) -> dict[str, Any]:
    if len(events) != expected_length:
        raise AuditError("ledger length does not match external commitment")
    previous = GENESIS_HASH
    idempotency_keys: set[str] = set()
    for index, event in enumerate(events, start=1):
        if event.get("sequence") != index:
            raise AuditError("audit sequence is invalid")
        if event.get("tenant_id") != expected_tenant:
            raise AuditError("audit tenant does not match expected tenant")
        if event.get("previous_hash") != previous:
            raise AuditError("previous hash link is invalid")
        key = event.get("idempotency_key")
        if not key or key in idempotency_keys:
            raise AuditError("replay detected in audit chain")
        if event.get("event_hash") != _hash_event(event):
            raise AuditError("event hash is invalid")
        idempotency_keys.add(key)
        previous = event["event_hash"]
    if previous != expected_head:
        raise AuditError("audit head does not match external commitment")
    return {
        "verified": True,
        "length": len(events),
        "head": previous,
        "tenant_id": expected_tenant,
    }
