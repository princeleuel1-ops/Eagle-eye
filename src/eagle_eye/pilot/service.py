"""Pilot runtime + HTTP API — the glue between the spine and the cockpit.

One PilotRuntime owns the durable storage, object store, signer, dev issuer,
identity verifier, ingestion boundary, shadow lifecycle, evaluator client,
health monitor, and metrics — and exposes them as a JSON API the cockpit
(and the smoke/failure-court drivers) call.

AUTH MODEL (no default bypass):
  every state-changing route requires  Authorization: Bearer <EE-SESSION>
  minted by the labeled local dev issuer; the verifier pins issuer, audience,
  tenant, expiry, nbf, revocation. Status/health/metrics and dev-token
  minting are the only open routes (the dev issuer is itself the
  NOT-PRODUCTION seam and its label travels in every response).

ERROR CONTRACT (stable for the UI's required states):
  401 identity failed/expired   403 permission denied
  404 unknown resource          409 lifecycle/duplicate refusals
  400 validation                503 dependency degraded (storage/evaluator)
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from ..identity import IdentityError
from .evaluator_service import EvaluatorClient, EvaluatorRefused, EvaluatorUnavailable
from .identity_service import (
    AuthorizationError, IdentityVerifier, LocalDevIssuer, PILOT_AUDIENCE,
    identity_status, require_permission)
from .ingest import IngestBoundary, SyntheticConnector
from .kms import EphemeralKeyProvider, kms_status
from .objectstore import FsObjectStore, ObjectStoreError
from .observability import HealthMonitor, METRICS, bind_context, get_logger, log_event
from .shadow import EvidenceBindingError, ShadowError, ShadowLifecycle
from .storage import DuplicateIdempotencyKey, PilotStorage, StorageError
from . import PILOT_SPEC

_LOG = get_logger("pilot.service")

FIXTURE_TENANT = "tenant-fixture-a"

ACTION_CATALOG = [
    {"action_id": "expedite-alt-supplier", "label": "Expedite alternate supplier",
     "bounded": "purchase order shift ≤ 14 days of demand"},
    {"action_id": "reroute-lane", "label": "Reroute shipments to backup lane",
     "bounded": "≤ 2 lanes affected"},
    {"action_id": "buffer-inventory", "label": "Raise safety stock temporarily",
     "bounded": "≤ 20% buffer for one cycle"},
]


class ApiError(Exception):
    def __init__(self, status: int, message: str, *, state: str | None = None):
        super().__init__(message)
        self.status = status
        self.state = state


class PilotRuntime:
    """Everything the pilot API needs, rooted in one home directory."""

    def __init__(self, home: str | Path):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.storage = PilotStorage(self.home / "pilot.sqlite3")
        self.storage.migrate()
        self.storage.ensure_tenant(FIXTURE_TENANT, display_name="Pilot Fixture A",
                                   data_class="FIXTURE")
        self.objects = FsObjectStore(self.home / "objects")
        self.signer = EphemeralKeyProvider()
        self.issuer = LocalDevIssuer(tenants=[FIXTURE_TENANT])
        self.verifier = IdentityVerifier(registry_entries=self.issuer.registry_entries())
        self.connector = SyntheticConnector(source_id="syn-fixture",
                                            tenant_id=FIXTURE_TENANT, seed=20270006)
        self.ingest = IngestBoundary(
            self.storage, signer=self.signer,
            sources={"syn-fixture": self.connector.source_registration()})
        self.shadow = ShadowLifecycle(self.storage, signer=self.signer)
        from .ops import evaluator_socket_path
        self.evaluator = EvaluatorClient(
            evaluator_socket_path(self.home),
            self._evaluator_token(), timeout_s=10.0)
        self.health = HealthMonitor()
        self.health.register("storage", self._probe_storage)
        self.health.register("object_store", self._probe_objects)
        self.health.register("evaluator_service", self._probe_evaluator,
                             required=False)  # degraded, not dead, without it
        self.started_at = time.time()

    def _evaluator_token(self) -> str:
        token_file = self.home / "run" / "client.token"
        if token_file.exists():
            return token_file.read_text().strip()
        return "evaluator-not-provisioned"

    # -- health probes ---------------------------------------------------------
    def _probe_storage(self):
        try:
            status = self.storage.migration_status()
            return bool(status), f"sqlite migrations applied: {len(status)}"
        except Exception as exc:
            return False, f"storage error: {type(exc).__name__}"

    def _probe_objects(self):
        try:
            stats = self.objects.stats()
            return True, f"objects: {stats['objects']}"
        except Exception as exc:
            return False, f"object store error: {type(exc).__name__}"

    def _probe_evaluator(self):
        try:
            status = self.evaluator.request("status")
            return True, f"lifecycle {status['lifecycle']}, looks {status['looks_spent']}"
        except (EvaluatorUnavailable, EvaluatorRefused) as exc:
            return False, f"unavailable: {type(exc).__name__}"

    def close(self) -> None:
        self.storage.close()

    # -- auth -------------------------------------------------------------------
    def authenticate(self, headers: dict[str, str], *, tenant_id: str) -> dict[str, Any]:
        auth = headers.get("authorization") or headers.get("Authorization") or ""
        if not auth.startswith("Bearer "):
            raise ApiError(401, "missing bearer assertion", state="IDENTITY_REQUIRED")
        try:
            principal = self.verifier.verify(auth[len("Bearer "):],
                                             expected_tenant=tenant_id)
        except IdentityError as exc:
            message = str(exc)
            state = "IDENTITY_EXPIRED" if "expired" in message else (
                "TENANT_MISMATCH" if "tenant" in message else "IDENTITY_INVALID")
            raise ApiError(401, message, state=state) from exc
        bind_context(tenant_id=tenant_id, request_id=principal["session_id"])
        return principal

    # -- decision support --------------------------------------------------------
    def decision_preview(self, tenant_id: str, evidence_ids: list[str]) -> dict[str, Any]:
        """FIXTURE decision support over bound evidence: aggregate severity,
        top lane, a bounded action recommendation, and honest uncertainty
        notes. Labeled — this is the pilot glue, not a live claim."""
        if not evidence_ids:
            raise ApiError(400, "at least one evidence digest is required")
        signals = []
        for digest in evidence_ids:
            try:
                trace = self.ingest.provenance(tenant_id, digest)
            except KeyError as exc:
                raise ApiError(404, str(exc)) from exc
            event = trace["normalized_event"]
            if event["event_kind"] == "disruption_signal":
                signals.append(event)
        if not signals:
            raise ApiError(400, "no disruption signals among the bound evidence")
        by_lane: dict[str, list[float]] = {}
        for signal in signals:
            by_lane.setdefault(signal["payload"]["lane"], []).append(
                float(signal["payload"]["severity"]))
        lane, severities = max(by_lane.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
        mean_severity = round(sum(severities) / len(severities), 3)
        recommended = (ACTION_CATALOG[0] if mean_severity >= 0.6 else
                       ACTION_CATALOG[1] if mean_severity >= 0.3 else
                       ACTION_CATALOG[2])
        return {
            "spec": "eagle-eye-pilot-decision/6.0",
            "label": "FIXTURE_DECISION_SUPPORT",
            "tenant_id": tenant_id,
            "evidence_ids": sorted(set(evidence_ids)),
            "signals_considered": len(signals),
            "focus_lane": lane,
            "mean_severity": mean_severity,
            "recommended_action": recommended,
            "uncertainty": {
                "n_signals": len(signals),
                "note": ("severity aggregation over fixture signals; the sealed "
                         "Bayesian evaluation runs on the synthetic suites — no "
                         "live-data inference is claimed"),
                "evidence_class": "SYNTHETICALLY VERIFIED (fixture aggregation)",
            },
            "external_execution": False,
        }


# ---------------------------------------------------------------------------
# routing
# ---------------------------------------------------------------------------

class PilotApi:
    """Method+path router over PilotRuntime, transport-agnostic (the http
    server, the smoke driver, and the failure court all call handle())."""

    def __init__(self, runtime: PilotRuntime):
        self.runtime = runtime
        self.routes: list[tuple[str, re.Pattern, str | None, Callable]] = [
            ("GET", re.compile(r"^/api/pilot/status$"), None, self._status),
            ("GET", re.compile(r"^/api/pilot/health$"), None, self._health),
            ("GET", re.compile(r"^/api/pilot/ready$"), None, self._ready),
            ("GET", re.compile(r"^/api/pilot/metrics$"), None, self._metrics),
            ("POST", re.compile(r"^/api/pilot/dev-issuer/mint$"), None, self._mint),
            ("POST", re.compile(r"^/api/pilot/ingest/synthetic$"), "ingest:run", self._ingest_synthetic),
            ("POST", re.compile(r"^/api/pilot/ingest/envelope$"), "ingest:run", self._ingest_envelope),
            ("GET", re.compile(r"^/api/pilot/ingest/events$"), "ingest:read", self._ingest_events),
            ("GET", re.compile(r"^/api/pilot/ingest/quarantine$"), "ingest:read", self._ingest_quarantine),
            ("GET", re.compile(r"^/api/pilot/provenance/(?P<digest>[0-9a-f]{64})$"), "ingest:read", self._provenance),
            ("POST", re.compile(r"^/api/pilot/decision$"), "decision:read", self._decision),
            ("GET", re.compile(r"^/api/pilot/actions$"), "decision:read", self._actions_list),
            ("GET", re.compile(r"^/api/pilot/actions/(?P<rid>[\w-]+)$"), "decision:read", self._action_detail),
            ("POST", re.compile(r"^/api/pilot/actions/request$"), "action:request", self._action_request),
            ("POST", re.compile(r"^/api/pilot/actions/(?P<rid>[\w-]+)/approve$"), "action:approve", self._action_approve),
            ("POST", re.compile(r"^/api/pilot/actions/(?P<rid>[\w-]+)/reject$"), "action:approve", self._action_reject),
            ("POST", re.compile(r"^/api/pilot/actions/(?P<rid>[\w-]+)/dispatch$"), "action:request", self._action_dispatch),
            ("POST", re.compile(r"^/api/pilot/actions/(?P<rid>[\w-]+)/outcome$"), "outcome:record", self._action_outcome),
            ("POST", re.compile(r"^/api/pilot/actions/(?P<rid>[\w-]+)/replay$"), "replay:run", self._action_replay),
            ("POST", re.compile(r"^/api/pilot/actions/(?P<rid>[\w-]+)/export$"), "evidence:export", self._action_export),
            ("GET", re.compile(r"^/api/pilot/evaluator/status$"), "decision:read", self._evaluator_status),
            ("POST", re.compile(r"^/api/pilot/backup$"), "evidence:export", self._backup),
        ]

    # -- dispatch ------------------------------------------------------------------
    def handle(self, method: str, path: str, body: dict[str, Any] | None,
               headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
        started = time.perf_counter()
        try:
            for route_method, pattern, permission, handler in self.routes:
                match = pattern.match(path)
                if match and route_method == method:
                    principal = None
                    if permission is not None:
                        principal = self.runtime.authenticate(
                            headers, tenant_id=FIXTURE_TENANT)
                        try:
                            require_permission(principal, permission)
                        except AuthorizationError as exc:
                            raise ApiError(403, str(exc),
                                           state="PERMISSION_DENIED") from exc
                    result = handler(body or {}, principal, **match.groupdict())
                    METRICS.inc(f"api.{method}.ok")
                    return 200, result
            raise ApiError(404, f"no route {method} {path}")
        except ApiError as exc:
            METRICS.inc(f"api.error.{exc.status}")
            return exc.status, {"error": str(exc), "state": exc.state}
        except (ShadowError, EvidenceBindingError, DuplicateIdempotencyKey) as exc:
            METRICS.inc("api.error.409")
            state = ("EVIDENCE_VERIFICATION_FAILED"
                     if isinstance(exc, EvidenceBindingError) else "REFUSED")
            return 409, {"error": str(exc), "state": state}
        except EvaluatorUnavailable as exc:
            METRICS.inc("api.error.503")
            return 503, {"error": str(exc), "state": "EVALUATOR_UNAVAILABLE"}
        except EvaluatorRefused as exc:
            METRICS.inc("api.error.409")
            return 409, {"error": str(exc), "state": f"EVALUATOR_{exc.code}"}
        except (StorageError, ObjectStoreError) as exc:
            METRICS.inc("api.error.503")
            return 503, {"error": f"{type(exc).__name__}: {exc}",
                         "state": "DEPENDENCY_DEGRADED"}
        finally:
            METRICS.observe("api.request", time.perf_counter() - started)

    # -- open routes ------------------------------------------------------------------
    def _status(self, body, principal):
        from ..adapters import pilot_status
        return {
            "spec": PILOT_SPEC,
            "tenant_id": FIXTURE_TENANT,
            "data_class": "FIXTURE",
            "external_execution": False,
            "adapters": pilot_status(),
            "identity": identity_status(self.runtime.issuer),
            "kms": kms_status(),
            "health": self.runtime.health.report(),
            "uptime_s": round(time.time() - self.runtime.started_at, 1),
        }

    def _health(self, body, principal):
        return self.runtime.health.report()

    def _ready(self, body, principal):
        report = self.runtime.health.report()
        if not report["ready"]:
            raise ApiError(503, "required dependencies degraded",
                           state="DEPENDENCY_DEGRADED")
        return {"ready": True}

    def _metrics(self, body, principal):
        return METRICS.snapshot()

    def _mint(self, body, principal):
        subject = body.get("subject")
        roles = body.get("roles")
        if not subject or not isinstance(roles, list) or not roles:
            raise ApiError(400, "subject and roles are required")
        token = self.runtime.issuer.mint(
            subject=str(subject), tenant_id=FIXTURE_TENANT,
            roles=[str(r) for r in roles],
            ttl_seconds=int(body.get("ttl_seconds", 600)))
        return {"token": token, "issuer": self.runtime.issuer.issuer,
                "warning": "NOT-PRODUCTION development issuer",
                "audience": PILOT_AUDIENCE}

    # -- ingest ------------------------------------------------------------------------
    def _ingest_synthetic(self, body, principal):
        count = int(body.get("count", 6))
        if not 1 <= count <= 200:
            raise ApiError(400, "count must be in [1,200]")
        import secrets as _secrets
        batch = _secrets.token_hex(4)  # fresh idempotency keys per batch
        results = []
        for envelope in self.runtime.connector.events(
                count, start_at=time.time() - count * 60, batch=batch):
            results.append(self.runtime.ingest.ingest_envelope(FIXTURE_TENANT, envelope))
        accepted = [r for r in results if r.get("accepted")]
        return {"requested": count, "accepted": len(accepted),
                "rejected": len(results) - len(accepted),
                "digests": [r["digest"] for r in accepted],
                "results": results}

    def _ingest_envelope(self, body, principal):
        return self.runtime.ingest.ingest_envelope(FIXTURE_TENANT,
                                                   body.get("envelope"))

    def _ingest_events(self, body, principal):
        events = self.runtime.ingest.normalized_events(FIXTURE_TENANT)
        return {"events": events, "count": len(events)}

    def _ingest_quarantine(self, body, principal):
        entries = self.runtime.ingest.quarantine_entries(FIXTURE_TENANT)
        return {"entries": entries, "count": len(entries)}

    def _provenance(self, body, principal, digest):
        try:
            return self.runtime.ingest.provenance(FIXTURE_TENANT, digest)
        except KeyError as exc:
            raise ApiError(404, str(exc)) from exc

    # -- decisions + actions ---------------------------------------------------------------
    def _decision(self, body, principal):
        return self.runtime.decision_preview(FIXTURE_TENANT,
                                             list(body.get("evidence_ids") or []))

    def _actions_list(self, body, principal):
        rows = self.runtime.storage.execute(
            FIXTURE_TENANT,
            "SELECT request_id, action_id, state, requester_id, requested_at, "
            "updated_at FROM action_state WHERE tenant_id=? ORDER BY requested_at DESC",
            (FIXTURE_TENANT,))
        return {"actions": [dict(r) for r in rows]}

    def _action_detail(self, body, principal, rid):
        try:
            row = self.runtime.shadow._row(FIXTURE_TENANT, rid)
        except ShadowError as exc:
            raise ApiError(404, str(exc)) from exc
        detail = {key: (json.loads(row[key]) if row.get(key) else None)
                  for key in ("request_json", "approval_json", "dispatch_json",
                              "outcome_json", "replay_json")}
        return {"request_id": rid, "state": row["state"],
                "requester_id": row["requester_id"],
                "evidence_digest": row["evidence_digest"],
                "approval_expires_at": row["approval_expires_at"],
                "timeline": self.runtime.shadow.timeline(FIXTURE_TENANT, rid),
                **{k.replace("_json", ""): v for k, v in detail.items()}}

    def _action_request(self, body, principal):
        evidence_ids = list(body.get("evidence_ids") or [])
        action_id = str(body.get("action_id") or "expedite-alt-supplier")
        if action_id not in {a["action_id"] for a in ACTION_CATALOG}:
            raise ApiError(400, f"action_id must be one of the bounded catalog")
        summary = str(body.get("summary") or "")[:500]
        return self.runtime.shadow.request(principal=principal, action_id=action_id,
                                           evidence_ids=evidence_ids, summary=summary)

    def _action_approve(self, body, principal, rid):
        return self.runtime.shadow.approve(
            principal=principal, request_id=rid,
            expires_in_s=float(body.get("expires_in_s", 3600.0)))

    def _action_reject(self, body, principal, rid):
        return self.runtime.shadow.reject(principal=principal, request_id=rid,
                                          reason=str(body.get("reason") or "")[:300])

    def _action_dispatch(self, body, principal, rid):
        key = body.get("idempotency_key")
        if not key:
            raise ApiError(400, "idempotency_key is required")
        return self.runtime.shadow.dispatch(principal=principal, request_id=rid,
                                            idempotency_key=str(key))

    def _action_outcome(self, body, principal, rid):
        observed = body.get("observed")
        if not isinstance(observed, dict):
            raise ApiError(400, "observed outcome object is required")
        return self.runtime.shadow.record_outcome(
            principal=principal, request_id=rid, observed=observed,
            outcome_source=str(body.get("outcome_source") or "fixture_observation"))

    def _action_replay(self, body, principal, rid):
        return self.runtime.shadow.replay(principal=principal, request_id=rid)

    def _action_export(self, body, principal, rid):
        return self.runtime.shadow.export_evidence_room(
            principal=principal, request_id=rid,
            object_store=self.runtime.objects)

    # -- evaluator + ops ----------------------------------------------------------------------
    def _evaluator_status(self, body, principal):
        try:
            return self.runtime.evaluator.request("status")
        except EvaluatorUnavailable as exc:
            raise  # handled as 503 EVALUATOR_UNAVAILABLE by the dispatcher

    def _backup(self, body, principal):
        dest = self.runtime.home / "backups" / time.strftime("%Y%m%dT%H%M%S")
        manifest = self.runtime.storage.backup(
            dest, object_store_dir=self.runtime.objects.root,
            signer=self.runtime.signer)
        log_event(_LOG, "backup created", dest=str(dest),
                  db_sha256=manifest["db_sha256"])
        return {"backup_dir": str(dest), "manifest": manifest}
