"""V5 pilot adapter seam — fail-closed boundaries for a future authorized pilot.

These are INTERFACES with a single safe default: disabled. They exist so a
pilot can wire real infrastructure at four clearly-labeled seams WITHOUT the
codebase pretending any of it exists today. Every adapter here is a
NullAdapter that raises `AdapterDisabled` on any privileged operation, and
`pilot_status()` reports exactly what a real pilot still needs.

CLAIM DISCIPLINE (do not violate):
  - live customer data ......... NOT ESTABLISHED (NullDataSource)
  - production identity/KMS ..... NOT ESTABLISHED (NullKeyCustody / NullIdentity)
  - durable transparency store .. NOT ESTABLISHED (NullAuditSink)
  - real external execution ..... NOT ESTABLISHED (NullActionExecutor)
Wiring a real backend is the pilot's job; these seams only make that wiring a
localized, reviewable change and keep the default fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class AdapterDisabled(RuntimeError):
    """Raised when a privileged adapter operation is attempted while the
    adapter is in its safe default (disabled) state."""


@runtime_checkable
class DataSource(Protocol):
    """Authorized live disruption/registry data. Default impl is disabled."""
    def is_live(self) -> bool: ...
    def fetch_tasks(self, *, tenant_id: str) -> list[dict[str, Any]]: ...


@runtime_checkable
class KeyCustody(Protocol):
    """Signing-key custody. A production pilot binds this to a KMS/HSM."""
    def is_production(self) -> bool: ...
    def sign(self, payload: bytes, *, key_id: str) -> bytes: ...


@runtime_checkable
class IdentityProvider(Protocol):
    """Principal authentication for requester/approver separation."""
    def is_production(self) -> bool: ...
    def authenticate(self, token: str) -> dict[str, Any]: ...


@runtime_checkable
class AuditSink(Protocol):
    """Durable, externally-anchored transparency storage for audit chains."""
    def is_durable(self) -> bool: ...
    def append(self, row: dict[str, Any]) -> str: ...


@runtime_checkable
class ActionExecutor(Protocol):
    """Real external execution (procurement, notifications). Fail-closed."""
    def is_enabled(self) -> bool: ...
    def execute(self, action: dict[str, Any]) -> dict[str, Any]: ...


class _Null:
    _WHAT = "adapter"

    def _blocked(self, op: str):
        raise AdapterDisabled(
            f"{self._WHAT}: '{op}' refused — no production backend is wired "
            "(V5 ships fail-closed; see PILOT_READINESS_CHECKLIST.md)")


class NullDataSource(_Null):
    _WHAT = "live data source"
    def is_live(self) -> bool: return False
    def fetch_tasks(self, *, tenant_id: str): self._blocked("fetch_tasks")


class NullKeyCustody(_Null):
    _WHAT = "production key custody"
    def is_production(self) -> bool: return False
    def sign(self, payload: bytes, *, key_id: str): self._blocked("sign")


class NullIdentity(_Null):
    _WHAT = "production identity provider"
    def is_production(self) -> bool: return False
    def authenticate(self, token: str): self._blocked("authenticate")


class NullAuditSink(_Null):
    _WHAT = "durable audit sink"
    def is_durable(self) -> bool: return False
    def append(self, row: dict[str, Any]): self._blocked("append")


class NullActionExecutor(_Null):
    _WHAT = "external action executor"
    def is_enabled(self) -> bool: return False
    def execute(self, action: dict[str, Any]): self._blocked("execute")


@dataclass(frozen=True)
class PilotConfig:
    """Every switch defaults OFF. Flipping one on without a real backend still
    fails closed, because the Null adapters ignore the flag and raise."""
    data_source_live: bool = False
    key_custody_production: bool = False
    identity_production: bool = False
    audit_sink_durable: bool = False
    external_execution_enabled: bool = False


def default_adapters() -> dict[str, Any]:
    """The ONLY adapter set V5 ships: all Null, all fail-closed."""
    return {
        "data_source": NullDataSource(),
        "key_custody": NullKeyCustody(),
        "identity": NullIdentity(),
        "audit_sink": NullAuditSink(),
        "action_executor": NullActionExecutor(),
    }


def pilot_status(adapters: dict[str, Any] | None = None,
                 config: PilotConfig | None = None) -> dict[str, Any]:
    """Machine-readable statement of exactly what a real pilot still needs.
    Honest by construction: reads the adapters' own capability reporters."""
    a = adapters or default_adapters()
    cfg = config or PilotConfig()
    needs = {
        "authorized_live_data": {
            "ready": a["data_source"].is_live(),
            "evidence_class": "NOT ESTABLISHED",
            "pilot_needs": "an authorized tenant data feed bound to DataSource"},
        "production_key_custody": {
            "ready": a["key_custody"].is_production(),
            "evidence_class": "NOT ESTABLISHED",
            "pilot_needs": "KMS/HSM-backed KeyCustody (V5 uses fixture Ed25519 keys)"},
        "production_identity": {
            "ready": a["identity"].is_production(),
            "evidence_class": "NOT ESTABLISHED",
            "pilot_needs": "SSO/OIDC IdentityProvider for requester/approver principals"},
        "durable_transparency_store": {
            "ready": a["audit_sink"].is_durable(),
            "evidence_class": "NOT ESTABLISHED",
            "pilot_needs": "append-only external store (e.g. transparency log) bound to AuditSink"},
        "external_execution": {
            "ready": a["action_executor"].is_enabled(),
            "evidence_class": "NOT ESTABLISHED",
            "pilot_needs": "authorized ActionExecutor; MUST stay off until legally/operationally cleared"},
    }
    return {
        "spec": "pilot-adapter-status/5.0",
        "all_fail_closed": not any(v["ready"] for v in needs.values()),
        "external_action": cfg.external_execution_enabled and a["action_executor"].is_enabled(),
        "capabilities": needs,
        "honesty": "V5 ships only Null adapters; every capability above is NOT ESTABLISHED "
                   "until a pilot wires and independently verifies a real backend.",
    }
