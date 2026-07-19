"""Shadow execution lifecycle — the complete human-gated action loop.

    REQUESTED → AWAITING_INDEPENDENT_APPROVAL → APPROVED_SHADOW
    → SHADOW_DISPATCHED → OUTCOME_PENDING → OUTCOME_RECORDED → REPLAY_VERIFIED

with terminal branches APPROVAL_REJECTED, EXPIRED, and EVIDENCE_FAILED.

ENFORCED (each with a rejection test):
  - no state transition without an authenticated, authorized principal
  - transition legality is a fixed map; skipping is impossible (the durable
    compare-and-set refuses any transition whose from-state is stale)
  - every transition lands in the tenant's append-only audit chain AND the
    shadow_transitions table (both durable)
  - independent approval: dual control via eagle_eye.governance (requester
    may never approve; approver role required; tenant pinned) — subject
    identities appear in every receipt
  - approvals expire; dispatch after expiry transitions to EXPIRED, refused
  - evidence binding is digest-frozen at request time and re-verified at
    approval AND dispatch; any drift is EVIDENCE_FAILED (fail closed)
  - dispatch is idempotent: the same idempotency key returns the SAME
    dispatch receipt; a different key for an already-dispatched action is
    refused (duplicate-message defense)
  - outcome capture records resolver identity + provenance and feeds the
    post-outcome decision-quality update
  - REPLAY recomputes the whole decision trail independently and only then
    marks REPLAY_VERIFIED
  - external execution: the ONLY executor wired is fail-closed
    (eagle_eye.adapters.NullActionExecutor); every receipt carries
    external_execution: false. The interface for a future authorized
    executor exists — its default implementation raises.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import secrets
import time
import zipfile
from typing import Any

from ..adapters import AdapterDisabled, NullActionExecutor
from ..audit import verify_chain
from ..governance import ApprovalError, approve_action, request_action
from .identity_service import require_permission
from .observability import METRICS, get_logger, log_event
from .storage import DuplicateIdempotencyKey, PilotStorage

SHADOW_SPEC = "eagle-eye-pilot-shadow/6.0"

STATES = ("REQUESTED", "AWAITING_INDEPENDENT_APPROVAL", "APPROVED_SHADOW",
          "SHADOW_DISPATCHED", "OUTCOME_PENDING", "OUTCOME_RECORDED",
          "REPLAY_VERIFIED", "APPROVAL_REJECTED", "EXPIRED", "EVIDENCE_FAILED")

ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "REQUESTED": ("AWAITING_INDEPENDENT_APPROVAL",),
    "AWAITING_INDEPENDENT_APPROVAL": ("APPROVED_SHADOW", "APPROVAL_REJECTED",
                                      "EVIDENCE_FAILED"),
    "APPROVED_SHADOW": ("SHADOW_DISPATCHED", "EXPIRED", "EVIDENCE_FAILED"),
    "SHADOW_DISPATCHED": ("OUTCOME_PENDING",),
    "OUTCOME_PENDING": ("OUTCOME_RECORDED",),
    "OUTCOME_RECORDED": ("REPLAY_VERIFIED",),
    "REPLAY_VERIFIED": (),
    "APPROVAL_REJECTED": (),
    "EXPIRED": (),
    "EVIDENCE_FAILED": (),
}

_LOG = get_logger("pilot.shadow")


class ShadowError(RuntimeError):
    """Refused lifecycle operation (fail closed, reason carried)."""


class EvidenceBindingError(ShadowError):
    """The evidence bound at request time no longer verifies."""


class ExternalExecutionDisabled(ShadowError):
    """The external executor is fail-closed (the only shipped state)."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class ShadowLifecycle:
    """Durable, tenant-bound action lifecycle over PilotStorage."""

    def __init__(self, storage: PilotStorage, *, signer,
                 external_executor=None):
        self.storage = storage
        self.signer = signer
        # The ONLY default is the fail-closed Null executor. Passing a real
        # one is a pilot decision that carries its own authorization trail.
        self.external_executor = external_executor or NullActionExecutor()

    # -- evidence binding ---------------------------------------------------------
    def evidence_digest(self, tenant_id: str, evidence_ids: list[str]) -> str:
        """Deterministic digest over the CONTENT of every bound evidence
        record (not just the ids): substitution after approval is detectable
        even if ids are unchanged."""
        parts = []
        for digest in sorted(set(evidence_ids)):
            row = self.storage.execute(
                tenant_id,
                "SELECT canonical_json FROM ingest_events WHERE tenant_id=? AND digest=?",
                (tenant_id, digest)).fetchone()
            if row is None:
                raise EvidenceBindingError(
                    f"evidence {digest[:12]}… is not an ingested record")
            parts.append({"digest": digest,
                          "content_sha256": _sha256(row["canonical_json"].encode())})
        return _sha256(_canonical(parts))

    def _verify_evidence(self, tenant_id: str, request_row: dict[str, Any]) -> None:
        request = json.loads(request_row["request_json"])
        recomputed = self.evidence_digest(tenant_id, request["evidence_ids"])
        if recomputed != request_row["evidence_digest"]:
            self._transition(tenant_id, request_row["request_id"],
                             request_row["state"], "EVIDENCE_FAILED",
                             actor_id="system:evidence-verifier",
                             note="evidence binding changed after request")
            raise EvidenceBindingError(
                "evidence binding no longer verifies — the action is frozen "
                "in EVIDENCE_FAILED and can never dispatch")

    # -- transitions --------------------------------------------------------------
    def _transition(self, tenant_id: str, request_id: str, from_state: str,
                    to_state: str, *, actor_id: str, note: str = "") -> None:
        if to_state not in ALLOWED_TRANSITIONS.get(from_state, ()):
            raise ShadowError(
                f"illegal transition {from_state} → {to_state} (no skipping)")
        audit_event = self.storage.audit_append(
            tenant_id, event_type="SHADOW_TRANSITION",
            actor_id=actor_id,
            payload={"request_id": request_id, "from": from_state,
                     "to": to_state, "note": note},
            idempotency_key=f"transition:{request_id}:{from_state}->{to_state}",
            signer=self.signer)
        with self.storage.transaction() as conn:
            cursor = conn.execute(
                "UPDATE action_state SET state=?, updated_at=? "
                "WHERE tenant_id=? AND request_id=? AND state=?",
                (to_state, time.time(), tenant_id, request_id, from_state))
            if cursor.rowcount != 1:
                raise ShadowError(
                    f"transition lost the race: state is no longer {from_state}")
            conn.execute(
                "INSERT INTO shadow_transitions "
                "(tenant_id, request_id, from_state, to_state, actor_id, "
                " audit_sequence, at) VALUES (?,?,?,?,?,?,?)",
                (tenant_id, request_id, from_state, to_state, actor_id,
                 audit_event["sequence"], time.time()))
        METRICS.inc(f"shadow.transition.{to_state}")
        log_event(_LOG, "shadow transition", tenant_id=tenant_id,
                  request_id=request_id, from_state=from_state, to_state=to_state)

    def _row(self, tenant_id: str, request_id: str) -> dict[str, Any]:
        row = self.storage.execute(
            tenant_id,
            "SELECT * FROM action_state WHERE tenant_id=? AND request_id=?",
            (tenant_id, request_id)).fetchone()
        if row is None:
            raise ShadowError(f"unknown action request {request_id!r}")
        return dict(row)

    def state_of(self, tenant_id: str, request_id: str) -> str:
        return self._row(tenant_id, request_id)["state"]

    def timeline(self, tenant_id: str, request_id: str) -> list[dict[str, Any]]:
        rows = self.storage.execute(
            tenant_id,
            "SELECT from_state, to_state, actor_id, audit_sequence, at "
            "FROM shadow_transitions WHERE tenant_id=? AND request_id=? "
            "ORDER BY transition_id", (tenant_id, request_id))
        return [dict(r) for r in rows]

    # -- 1. request -------------------------------------------------------------------
    def request(self, *, principal: dict[str, Any], action_id: str,
                evidence_ids: list[str], summary: str) -> dict[str, Any]:
        require_permission(principal, "action:request")
        tenant_id = principal["tenant_id"]
        if not evidence_ids:
            raise ShadowError("an action request must bind at least one evidence record")
        evidence_digest = self.evidence_digest(tenant_id, evidence_ids)
        action = {"id": action_id, "tenant_id": tenant_id, "mode": "FIXTURE",
                  "status": "pending_approval", "evidence_ids": evidence_ids}
        request = request_action(action, principal=principal)  # dual-control receipt
        request["summary"] = summary
        request["evidence_digest"] = evidence_digest
        request_id = request["request_id"]
        with self.storage.transaction() as conn:
            conn.execute(
                "INSERT INTO action_state "
                "(tenant_id, request_id, action_id, state, requester_id, "
                " evidence_digest, request_json, approval_json, dispatch_json, "
                " outcome_json, replay_json, requested_at, approval_expires_at, "
                " updated_at) VALUES (?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,?,NULL,?)",
                (tenant_id, request_id, action_id, "REQUESTED", principal["id"],
                 evidence_digest, json.dumps(request, sort_keys=True),
                 time.time(), time.time()))
        self.storage.audit_append(
            tenant_id, event_type="ACTION_REQUESTED", actor_id=principal["id"],
            payload={"request_id": request_id, "action_id": action_id,
                     "evidence_digest": evidence_digest, "summary": summary},
            idempotency_key=f"request:{request_id}", signer=self.signer)
        self._transition(tenant_id, request_id, "REQUESTED",
                         "AWAITING_INDEPENDENT_APPROVAL",
                         actor_id=principal["id"])
        return {"request_id": request_id, "state": "AWAITING_INDEPENDENT_APPROVAL",
                "evidence_digest": evidence_digest, "request": request}

    # -- 2. independent approval ---------------------------------------------------------
    def approve(self, *, principal: dict[str, Any], request_id: str,
                expires_in_s: float = 3600.0) -> dict[str, Any]:
        require_permission(principal, "action:approve")
        tenant_id = principal["tenant_id"]
        row = self._row(tenant_id, request_id)
        if row["state"] != "AWAITING_INDEPENDENT_APPROVAL":
            raise ShadowError(f"approval refused in state {row['state']}")
        self._verify_evidence(tenant_id, row)
        request = json.loads(row["request_json"])
        try:
            receipt = approve_action(request, principal=principal)
        except ApprovalError as exc:
            raise ShadowError(f"approval refused: {exc}") from exc
        receipt["approval_expires_at"] = time.time() + expires_in_s
        receipt["external_execution"] = False
        # exactly one approval per request — a second one is a duplicate
        try:
            self.storage.claim_idempotency(tenant_id, scope="approval",
                                           key=request_id)
        except DuplicateIdempotencyKey as exc:
            raise ShadowError("duplicate approval refused") from exc
        with self.storage.transaction() as conn:
            conn.execute(
                "UPDATE action_state SET approval_json=?, approval_expires_at=? "
                "WHERE tenant_id=? AND request_id=?",
                (json.dumps(receipt, sort_keys=True),
                 receipt["approval_expires_at"], tenant_id, request_id))
        self.storage.audit_append(
            tenant_id, event_type="ACTION_APPROVED", actor_id=principal["id"],
            payload={"request_id": request_id, "approver_id": principal["id"],
                     "requester_id": row["requester_id"],
                     "expires_at": receipt["approval_expires_at"]},
            idempotency_key=f"approve:{request_id}", signer=self.signer)
        self._transition(tenant_id, request_id, "AWAITING_INDEPENDENT_APPROVAL",
                         "APPROVED_SHADOW", actor_id=principal["id"])
        return {"request_id": request_id, "state": "APPROVED_SHADOW",
                "approval": receipt}

    def reject(self, *, principal: dict[str, Any], request_id: str,
               reason: str) -> dict[str, Any]:
        require_permission(principal, "action:approve")
        tenant_id = principal["tenant_id"]
        row = self._row(tenant_id, request_id)
        if row["state"] != "AWAITING_INDEPENDENT_APPROVAL":
            raise ShadowError(f"rejection refused in state {row['state']}")
        self.storage.audit_append(
            tenant_id, event_type="ACTION_REJECTED", actor_id=principal["id"],
            payload={"request_id": request_id, "reason": reason},
            idempotency_key=f"reject:{request_id}", signer=self.signer)
        self._transition(tenant_id, request_id, "AWAITING_INDEPENDENT_APPROVAL",
                         "APPROVAL_REJECTED", actor_id=principal["id"],
                         note=reason)
        return {"request_id": request_id, "state": "APPROVAL_REJECTED"}

    # -- 3. shadow dispatch -----------------------------------------------------------------
    def dispatch(self, *, principal: dict[str, Any], request_id: str,
                 idempotency_key: str) -> dict[str, Any]:
        require_permission(principal, "action:request")
        tenant_id = principal["tenant_id"]
        row = self._row(tenant_id, request_id)
        # idempotent dispatch: same key ⇒ same receipt, no second transition
        if row["dispatch_json"]:
            existing = json.loads(row["dispatch_json"])
            if existing.get("idempotency_key") == idempotency_key:
                return {"request_id": request_id, "state": row["state"],
                        "dispatch": existing, "idempotent_replay": True}
            raise ShadowError("action already dispatched (duplicate message refused)")
        if row["state"] != "APPROVED_SHADOW":
            raise ShadowError(f"dispatch refused in state {row['state']}")
        if time.time() > (row["approval_expires_at"] or 0):
            self._transition(tenant_id, request_id, "APPROVED_SHADOW", "EXPIRED",
                             actor_id="system:expiry",
                             note="approval expired before dispatch")
            raise ShadowError("approval expired; action moved to EXPIRED")
        self._verify_evidence(tenant_id, row)
        # external execution stays fail-closed and PROVABLY so:
        external_state: dict[str, Any] = {"enabled": self.external_executor.is_enabled()}
        if external_state["enabled"]:  # pragma: no cover — never true in V6
            raise ExternalExecutionDisabled(
                "an enabled external executor is not a shippable V6 state")
        try:
            self.external_executor.execute({"request_id": request_id})
            raise ShadowError("external executor unexpectedly executed")
        except AdapterDisabled as exc:
            external_state["fail_closed_proof"] = str(exc)[:120]
        try:
            self.storage.claim_idempotency(tenant_id, scope="dispatch",
                                           key=idempotency_key)
        except DuplicateIdempotencyKey as exc:
            raise ShadowError("dispatch idempotency key already used "
                              "for a different action") from exc
        dispatch = {
            "dispatch_id": f"shadow-{secrets.token_hex(8)}",
            "request_id": request_id,
            "mode": "SHADOW",
            "external_execution": False,
            "external_executor_state": external_state,
            "dispatched_by": principal["id"],
            "dispatched_at": time.time(),
            "idempotency_key": idempotency_key,
        }
        dispatch["dispatch_hash"] = _sha256(_canonical(dispatch))
        dispatch["signature_b64"] = base64.b64encode(
            self.signer.sign(dispatch["dispatch_hash"].encode())).decode()
        with self.storage.transaction() as conn:
            conn.execute(
                "UPDATE action_state SET dispatch_json=? WHERE tenant_id=? AND request_id=?",
                (json.dumps(dispatch, sort_keys=True), tenant_id, request_id))
        self.storage.audit_append(
            tenant_id, event_type="SHADOW_DISPATCHED", actor_id=principal["id"],
            payload={"request_id": request_id, "dispatch_id": dispatch["dispatch_id"],
                     "external_execution": False},
            idempotency_key=f"dispatch:{request_id}", signer=self.signer)
        self._transition(tenant_id, request_id, "APPROVED_SHADOW",
                         "SHADOW_DISPATCHED", actor_id=principal["id"])
        self._transition(tenant_id, request_id, "SHADOW_DISPATCHED",
                         "OUTCOME_PENDING", actor_id="system:outcome-tracker")
        return {"request_id": request_id, "state": "OUTCOME_PENDING",
                "dispatch": dispatch}

    # -- 4. outcome capture --------------------------------------------------------------------
    def record_outcome(self, *, principal: dict[str, Any], request_id: str,
                       observed: dict[str, Any],
                       outcome_source: str = "fixture_observation") -> dict[str, Any]:
        require_permission(principal, "outcome:record")
        tenant_id = principal["tenant_id"]
        row = self._row(tenant_id, request_id)
        if row["state"] != "OUTCOME_PENDING":
            raise ShadowError(f"outcome refused in state {row['state']}")
        outcome = {
            "outcome_id": f"outcome-{secrets.token_hex(8)}",
            "request_id": request_id,
            "observed": observed,
            "outcome_source": outcome_source,
            "resolver_id": principal["id"],
            "recorded_at": time.time(),
            "decision_quality": self._decision_quality(observed),
        }
        outcome["outcome_hash"] = _sha256(_canonical(outcome))
        outcome["signature_b64"] = base64.b64encode(
            self.signer.sign(outcome["outcome_hash"].encode())).decode()
        with self.storage.transaction() as conn:
            conn.execute(
                "UPDATE action_state SET outcome_json=? WHERE tenant_id=? AND request_id=?",
                (json.dumps(outcome, sort_keys=True), tenant_id, request_id))
        self.storage.audit_append(
            tenant_id, event_type="OUTCOME_RECORDED", actor_id=principal["id"],
            payload={"request_id": request_id, "outcome_id": outcome["outcome_id"],
                     "outcome_source": outcome_source,
                     "decision_quality": outcome["decision_quality"]},
            idempotency_key=f"outcome:{request_id}", signer=self.signer)
        self._transition(tenant_id, request_id, "OUTCOME_PENDING",
                         "OUTCOME_RECORDED", actor_id=principal["id"])
        METRICS.inc("shadow.outcomes_recorded")
        return {"request_id": request_id, "state": "OUTCOME_RECORDED",
                "outcome": outcome}

    @staticmethod
    def _decision_quality(observed: dict[str, Any]) -> dict[str, Any]:
        """Post-outcome decision-quality update on the SHADOW decision:
        an honest local calibration record (labeled), not a live claim."""
        predicted = observed.get("predicted_delay_days")
        actual = observed.get("actual_delay_days")
        entry: dict[str, Any] = {"label": "SHADOW_FIXTURE_CALIBRATION"}
        if isinstance(predicted, (int, float)) and isinstance(actual, (int, float)):
            entry["abs_error_days"] = round(abs(predicted - actual), 3)
            entry["within_20pct"] = bool(
                abs(predicted - actual) <= 0.2 * max(actual, 1e-9))
        else:
            entry["abs_error_days"] = None
            entry["within_20pct"] = None
        return entry

    # -- 5. replay -------------------------------------------------------------------------------
    def replay(self, *, principal: dict[str, Any], request_id: str) -> dict[str, Any]:
        require_permission(principal, "replay:run")
        tenant_id = principal["tenant_id"]
        row = self._row(tenant_id, request_id)
        if row["state"] not in ("OUTCOME_RECORDED", "REPLAY_VERIFIED"):
            raise ShadowError(f"replay requires a recorded outcome (state {row['state']})")
        checks: dict[str, bool] = {}
        # 1. evidence binding still verifies from durable content
        request = json.loads(row["request_json"])
        checks["evidence_binding"] = (
            self.evidence_digest(tenant_id, request["evidence_ids"])
            == row["evidence_digest"])
        # 2. the tenant audit chain verifies end-to-end against the head
        events = self.storage.audit_events(tenant_id)
        length, head = self.storage.audit_head(tenant_id)
        try:
            verify_chain(events, expected_tenant=tenant_id,
                         expected_head=head, expected_length=length)
            checks["audit_chain"] = True
        except Exception:
            checks["audit_chain"] = False
        # 3. the transition timeline is exactly a legal path
        timeline = self.timeline(tenant_id, request_id)
        legal = bool(timeline)
        for step in timeline:
            if step["to_state"] not in ALLOWED_TRANSITIONS.get(step["from_state"], ()):
                legal = False
        checks["transition_legality"] = legal
        # 4. dual control: approver ≠ requester, both present in receipts
        approval = json.loads(row["approval_json"]) if row["approval_json"] else {}
        checks["dual_control"] = bool(
            approval and approval.get("approver_id")
            and approval.get("approver_id") != row["requester_id"])
        # 5. dispatch and outcome signatures verify with the pilot signer
        ok_sigs = True
        for blob_key, hash_key in (("dispatch_json", "dispatch_hash"),
                                   ("outcome_json", "outcome_hash")):
            blob = json.loads(row[blob_key]) if row[blob_key] else None
            if not blob:
                ok_sigs = False
                continue
            signature = base64.b64decode(blob["signature_b64"])
            ok_sigs = ok_sigs and self.signer.verify(
                blob[hash_key].encode(), signature)
            recompute = {k: v for k, v in blob.items()
                         if k not in (hash_key, "signature_b64")}
            ok_sigs = ok_sigs and _sha256(_canonical(recompute)) == blob[hash_key]
        checks["signatures"] = ok_sigs
        # 6. external execution provably false end-to-end
        dispatch = json.loads(row["dispatch_json"]) if row["dispatch_json"] else {}
        checks["external_execution_false"] = dispatch.get("external_execution") is False
        replay_receipt = {
            "spec": "eagle-eye-pilot-replay/6.0",
            "request_id": request_id,
            "checks": checks,
            "verified": all(checks.values()),
            "replayed_by": principal["id"],
            "replayed_at": time.time(),
            "audit_head": head, "audit_length": length,
        }
        with self.storage.transaction() as conn:
            conn.execute(
                "UPDATE action_state SET replay_json=? WHERE tenant_id=? AND request_id=?",
                (json.dumps(replay_receipt, sort_keys=True), tenant_id, request_id))
        self.storage.audit_append(
            tenant_id, event_type="REPLAY_RUN", actor_id=principal["id"],
            payload={"request_id": request_id, "verified": replay_receipt["verified"],
                     "checks": checks},
            idempotency_key=f"replay:{request_id}:{length}", signer=self.signer)
        if replay_receipt["verified"] and row["state"] == "OUTCOME_RECORDED":
            self._transition(tenant_id, request_id, "OUTCOME_RECORDED",
                             "REPLAY_VERIFIED", actor_id=principal["id"])
        if not replay_receipt["verified"]:
            METRICS.inc("shadow.replay_failures")
        return replay_receipt

    # -- 6. exportable audit receipt ------------------------------------------------------------------
    def export_evidence_room(self, *, principal: dict[str, Any], request_id: str,
                             object_store) -> dict[str, Any]:
        """One self-contained zip: request, approval, dispatch, outcome,
        replay, bound evidence records, the FULL tenant audit chain, and the
        separately persisted head commitment. Stored content-addressed."""
        require_permission(principal, "evidence:export")
        tenant_id = principal["tenant_id"]
        row = self._row(tenant_id, request_id)
        request = json.loads(row["request_json"])
        evidence_records = []
        for digest in request["evidence_ids"]:
            record = self.storage.execute(
                tenant_id,
                "SELECT canonical_json, receipt_json FROM ingest_events "
                "WHERE tenant_id=? AND digest=?", (tenant_id, digest)).fetchone()
            if record is None:
                raise EvidenceBindingError(f"evidence {digest[:12]}… missing at export")
            evidence_records.append({"digest": digest,
                                     "event": json.loads(record["canonical_json"]),
                                     "receipt": json.loads(record["receipt_json"])})
        head_commitment = self.storage.latest_head_commitment(tenant_id)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            def add(name: str, payload: Any) -> None:
                archive.writestr(name, json.dumps(payload, indent=2, sort_keys=True))
            add("request.json", request)
            add("approval.json", json.loads(row["approval_json"]) if row["approval_json"] else None)
            add("dispatch.json", json.loads(row["dispatch_json"]) if row["dispatch_json"] else None)
            add("outcome.json", json.loads(row["outcome_json"]) if row["outcome_json"] else None)
            add("replay.json", json.loads(row["replay_json"]) if row["replay_json"] else None)
            add("evidence_records.json", evidence_records)
            add("audit_chain.json", self.storage.audit_events(tenant_id))
            add("audit_head_commitment.json", head_commitment)
            add("timeline.json", self.timeline(tenant_id, request_id))
            add("MANIFEST.json", {
                "spec": SHADOW_SPEC, "request_id": request_id,
                "tenant_id": tenant_id, "state": row["state"],
                "external_execution": False,
                "exported_by": principal["id"], "exported_at": time.time(),
                "signer_key_id": self.signer.key_id(),
            })
        data = buffer.getvalue()
        digest = object_store.put(data)
        self.storage.audit_append(
            tenant_id, event_type="EVIDENCE_ROOM_EXPORTED", actor_id=principal["id"],
            payload={"request_id": request_id, "object_digest": digest,
                     "bytes": len(data)},
            idempotency_key=f"export:{request_id}:{digest[:16]}", signer=self.signer)
        METRICS.inc("shadow.evidence_exports")
        return {"request_id": request_id, "object_digest": digest,
                "bytes": len(data), "state": row["state"]}
