"""Authorized ingestion contract — the pilot's only door for data.

Versioned event contract (eagle-eye-ingest-event/1.0):
  envelope = {
    "event": {
      "contract_version": "eagle-eye-ingest-event/1.0",
      "event_kind": "disruption_signal" | "registry_task" | "correction",
      "source_id": str, "tenant_id": str,
      "occurred_at": float epoch seconds,
      "idempotency_key": str,
      "payload": {…kind-specific…},
      "supersedes_digest": str | absent (corrections only),
    },
    "signature_b64": base64 Ed25519 over canonical(event),
    "key_id": signer key id,
  }

ENFORCED AT THE BOUNDARY (each with a rejection test):
  - explicit source authority: only registered sources, only their tenant,
    only their authorized kinds — unknown source ⇒ quarantine
  - source identity: every envelope must verify against the source's
    registered public key — unsigned/badly-signed ⇒ quarantine
  - schema validation per kind; malformed ⇒ quarantine with reasons
  - size abuse: raw payloads over MAX_EVENT_BYTES are refused BEFORE parsing
  - canonical normalization + content digest; duplicate content ⇒ replay
    rejection; duplicate idempotency key ⇒ transactional rejection
  - late events accepted but labeled; corrections must reference an existing
    digest and never mutate the superseded row (append-only provenance)
  - every acceptance emits a SIGNED ingestion receipt and an audit event;
    provenance is traceable from raw bytes to the normalized record

Connectors: deterministic synthetic (fixture), replayable file (jsonl/csv),
and a DISABLED HTTP/webhook interface that fails closed. No scraping, no
invented customer data — fixture tenants are labeled FIXTURE end-to-end.
"""

from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import random
import time
from pathlib import Path
from typing import Any, Iterator

from ..signing import sign as _sign, verify as _verify, key_id as _pem_key_id, generate_demo_keypair
from .observability import METRICS, get_logger, log_event
from .storage import DuplicateIdempotencyKey, PilotStorage

INGEST_CONTRACT = "eagle-eye-ingest-event/1.0"
EVENT_KINDS = ("disruption_signal", "registry_task", "correction")
MAX_EVENT_BYTES = 64 * 1024
LATE_WATERMARK_SECONDS = 7 * 24 * 3600

_LOG = get_logger("pilot.ingest")

PAYLOAD_SCHEMAS: dict[str, dict[str, type]] = {
    "disruption_signal": {"lane": str, "disruption_class": str,
                          "severity": float, "description": str},
    "registry_task": {"lane": str, "disruption_class": str,
                      "n_observations": int, "as_of_end": float},
    "correction": {"reason": str},
}


class ConnectorDisabled(RuntimeError):
    """The HTTP/webhook connector is present as an interface and refuses to
    serve until an authorized pilot explicitly wires and enables it."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    """Canonical normalization: stable field order, trimmed strings, floats
    for timestamps/severities. The digest is over THIS normalized form, so
    semantically identical submissions dedupe identically."""
    normalized = {
        "contract_version": event["contract_version"],
        "event_kind": event["event_kind"],
        "source_id": event["source_id"].strip(),
        "tenant_id": event["tenant_id"].strip(),
        "occurred_at": float(event["occurred_at"]),
        "payload": {k: (v.strip() if isinstance(v, str) else v)
                    for k, v in sorted(event["payload"].items())},
    }
    if "supersedes_digest" in event:
        normalized["supersedes_digest"] = event["supersedes_digest"]
    return normalized


def validate_event(event: Any) -> list[str]:
    """Pure schema validation. Returns a list of human-readable defects
    (empty ⇒ valid). Never raises — the boundary quarantines on defects."""
    problems: list[str] = []
    if not isinstance(event, dict):
        return ["event is not an object"]
    if event.get("contract_version") != INGEST_CONTRACT:
        problems.append(f"contract_version must be {INGEST_CONTRACT}")
    kind = event.get("event_kind")
    if kind not in EVENT_KINDS:
        problems.append(f"event_kind must be one of {EVENT_KINDS}")
    for field in ("source_id", "tenant_id", "idempotency_key"):
        if not isinstance(event.get(field), str) or not event.get(field, "").strip():
            problems.append(f"{field} is required")
    occurred = event.get("occurred_at")
    if not isinstance(occurred, (int, float)) or isinstance(occurred, bool) or occurred <= 0:
        problems.append("occurred_at must be positive epoch seconds")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        problems.append("payload must be an object")
    elif kind in PAYLOAD_SCHEMAS:
        for field, ftype in PAYLOAD_SCHEMAS[kind].items():
            value = payload.get(field)
            if ftype is float and isinstance(value, int) and not isinstance(value, bool):
                value = float(value)
            if not isinstance(value, ftype) or isinstance(value, bool):
                problems.append(f"payload.{field} must be {ftype.__name__}")
        if kind == "disruption_signal":
            severity = payload.get("severity")
            if isinstance(severity, (int, float)) and not 0.0 <= float(severity) <= 1.0:
                problems.append("payload.severity must be within [0,1]")
        if kind == "correction" and not isinstance(event.get("supersedes_digest"), str):
            problems.append("correction requires supersedes_digest")
    return problems


class IngestBoundary:
    """The tenant-bound ingestion service over durable storage."""

    def __init__(self, storage: PilotStorage, *, signer,
                 sources: dict[str, dict[str, Any]]):
        """sources: source_id → {public_key_pem: bytes, tenant_id: str,
        authorized_kinds: list[str], display_name: str}"""
        self.storage = storage
        self.signer = signer
        self.sources = sources

    # -- quarantine ------------------------------------------------------------
    def _quarantine(self, tenant_id: str, raw_excerpt: str, reasons: list[str],
                    source_id: str | None) -> dict[str, Any]:
        METRICS.inc("ingest.quarantined")
        with self.storage.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO ingest_quarantine "
                "(tenant_id, source_id, raw_excerpt, reasons_json, received_at) "
                "VALUES (?,?,?,?,?)",
                (tenant_id, source_id, raw_excerpt[:2000],
                 json.dumps(reasons), time.time()))
            quarantine_id = cursor.lastrowid
        log_event(_LOG, "ingest quarantined", tenant_id=tenant_id,
                  source_id=source_id, reasons=reasons)
        return {"accepted": False, "quarantine_id": quarantine_id,
                "reasons": reasons, "state": "QUARANTINED"}

    def quarantine_entries(self, tenant_id: str) -> list[dict[str, Any]]:
        rows = self.storage.execute(
            tenant_id,
            "SELECT quarantine_id, source_id, reasons_json, received_at "
            "FROM ingest_quarantine WHERE tenant_id=? ORDER BY quarantine_id",
            (tenant_id,))
        return [{"quarantine_id": r["quarantine_id"], "source_id": r["source_id"],
                 "reasons": json.loads(r["reasons_json"]),
                 "received_at": r["received_at"]} for r in rows]

    # -- the boundary ------------------------------------------------------------
    def ingest_raw(self, tenant_id: str, raw: bytes,
                   *, source_hint: str | None = None) -> dict[str, Any]:
        """Raw-bytes door: size cap BEFORE parse, JSON parse, then envelope."""
        if len(raw) > MAX_EVENT_BYTES:
            return self._quarantine(tenant_id, raw[:200].decode(errors="replace"),
                                    [f"payload exceeds {MAX_EVENT_BYTES} bytes "
                                     "(size/decompression abuse guard)"], source_hint)
        try:
            envelope = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return self._quarantine(tenant_id, raw[:200].decode(errors="replace"),
                                    [f"malformed JSON: {exc}"], source_hint)
        return self.ingest_envelope(tenant_id, envelope)

    def ingest_envelope(self, tenant_id: str, envelope: Any) -> dict[str, Any]:
        received_at = time.time()
        if not isinstance(envelope, dict) or not isinstance(envelope.get("event"), dict):
            return self._quarantine(tenant_id, json.dumps(envelope)[:200],
                                    ["envelope must contain an event object"], None)
        event = envelope["event"]
        source_id = event.get("source_id") if isinstance(event.get("source_id"), str) else None

        # 1. explicit source authority
        source = self.sources.get(source_id or "")
        if source is None:
            return self._quarantine(tenant_id, json.dumps(event)[:300],
                                    [f"unknown source {source_id!r} (no source authority)"],
                                    source_id)
        if source["tenant_id"] != tenant_id or event.get("tenant_id") != tenant_id:
            return self._quarantine(tenant_id, json.dumps(event)[:300],
                                    ["source/tenant binding mismatch"], source_id)

        # 2. source identity: the envelope must verify against the source key
        signature_b64 = envelope.get("signature_b64")
        key_id = envelope.get("key_id")
        if not signature_b64 or not key_id:
            return self._quarantine(tenant_id, json.dumps(event)[:300],
                                    ["unsigned ingestion refused (missing signature)"],
                                    source_id)
        expected_kid = _pem_key_id(source["public_key_pem"])
        if key_id != expected_kid:
            return self._quarantine(tenant_id, json.dumps(event)[:300],
                                    ["signature key does not match registered source key"],
                                    source_id)
        try:
            signature = base64.b64decode(signature_b64)
        except Exception:
            return self._quarantine(tenant_id, json.dumps(event)[:300],
                                    ["signature encoding invalid"], source_id)
        if not _verify(_canonical(event), signature, source["public_key_pem"]):
            return self._quarantine(tenant_id, json.dumps(event)[:300],
                                    ["source signature verification failed"], source_id)

        # 3. schema validation
        problems = validate_event(event)
        if problems:
            return self._quarantine(tenant_id, json.dumps(event)[:300], problems, source_id)
        if event["event_kind"] not in source.get("authorized_kinds", []):
            return self._quarantine(tenant_id, json.dumps(event)[:300],
                                    [f"source not authorized for kind {event['event_kind']!r}"],
                                    source_id)

        # 4. canonical normalization + content digest
        raw_sha = _sha256(_canonical(event))
        normalized = normalize_event(event)
        canonical = _canonical(normalized)
        digest = _sha256(canonical)

        # 5. corrections must reference an existing record
        supersedes = normalized.get("supersedes_digest")
        if event["event_kind"] == "correction":
            row = self.storage.execute(
                tenant_id,
                "SELECT digest FROM ingest_events WHERE tenant_id=? AND digest=?",
                (tenant_id, supersedes)).fetchone()
            if row is None:
                return self._quarantine(tenant_id, json.dumps(event)[:300],
                                        [f"correction references unknown digest "
                                         f"{str(supersedes)[:12]}…"], source_id)

        # 6. replay protection: duplicate CONTENT is a replay …
        existing = self.storage.execute(
            tenant_id,
            "SELECT digest FROM ingest_events WHERE tenant_id=? AND digest=?",
            (tenant_id, digest)).fetchone()
        if existing is not None:
            METRICS.inc("ingest.replayed")
            return {"accepted": False, "state": "REPLAY_REJECTED",
                    "digest": digest,
                    "reasons": ["identical content already ingested (replay protection)"]}
        # … and a reused idempotency key is rejected transactionally
        try:
            self.storage.claim_idempotency(tenant_id, scope="ingest",
                                           key=event["idempotency_key"])
        except DuplicateIdempotencyKey:
            METRICS.inc("ingest.duplicate_key")
            return {"accepted": False, "state": "DUPLICATE_IDEMPOTENCY_KEY",
                    "reasons": ["idempotency key already used"]}

        # 7. acceptance: durable row + signed receipt + audit event
        late = (received_at - normalized["occurred_at"]) > LATE_WATERMARK_SECONDS
        tenant_row = self.storage.tenant(tenant_id) or {}
        receipt = {
            "spec": "eagle-eye-ingest-receipt/6.0",
            "tenant_id": tenant_id,
            "data_class": tenant_row.get("data_class", "FIXTURE"),
            "source_id": source_id,
            "event_kind": normalized["event_kind"],
            "digest": digest,
            "raw_event_sha256": raw_sha,
            "normalization": "eagle-eye-ingest-normalize/1.0",
            "received_at": received_at,
            "late": late,
            "supersedes_digest": supersedes,
        }
        receipt_sig = base64.b64encode(self.signer.sign(_canonical(receipt))).decode()
        receipt["receipt_signature_b64"] = receipt_sig
        receipt["receipt_signer_key_id"] = self.signer.key_id()
        with self.storage.transaction() as conn:
            conn.execute(
                "INSERT INTO ingest_events VALUES (?,?,?,?,?,?,?,?,?)",
                (tenant_id, digest, source_id, INGEST_CONTRACT,
                 normalized["event_kind"], canonical.decode(),
                 supersedes, received_at, json.dumps(receipt, sort_keys=True)))
        self.storage.audit_append(
            tenant_id, event_type="INGEST_ACCEPTED", actor_id=f"source:{source_id}",
            payload={"digest": digest, "event_kind": normalized["event_kind"],
                     "late": late, "supersedes_digest": supersedes},
            idempotency_key=f"ingest:{digest}")
        METRICS.inc("ingest.accepted")
        log_event(_LOG, "ingest accepted", tenant_id=tenant_id,
                  source_id=source_id, digest=digest, late=late)
        return {"accepted": True, "state": "ACCEPTED", "digest": digest,
                "receipt": receipt}

    # -- reads ----------------------------------------------------------------------
    def normalized_events(self, tenant_id: str, *, kind: str | None = None) -> list[dict[str, Any]]:
        rows = self.storage.execute(
            tenant_id,
            "SELECT digest, event_kind, canonical_json, supersedes_digest, received_at "
            "FROM ingest_events WHERE tenant_id=? ORDER BY received_at",
            (tenant_id,))
        out = []
        superseded = set()
        records = [dict(r) for r in rows]
        for r in records:
            if r["supersedes_digest"]:
                superseded.add(r["supersedes_digest"])
        for r in records:
            event = json.loads(r["canonical_json"])
            if kind and event["event_kind"] != kind:
                continue
            out.append({"digest": r["digest"], "event": event,
                        "superseded_by_correction": r["digest"] in superseded,
                        "received_at": r["received_at"]})
        return out

    def provenance(self, tenant_id: str, digest: str) -> dict[str, Any]:
        """Raw → normalized trace for one record, fail-closed on absence."""
        row = self.storage.execute(
            tenant_id,
            "SELECT * FROM ingest_events WHERE tenant_id=? AND digest=?",
            (tenant_id, digest)).fetchone()
        if row is None:
            raise KeyError(f"no ingested record {digest[:12]}… for tenant")
        receipt = json.loads(row["receipt_json"])
        canonical = row["canonical_json"]
        recomputed = _sha256(canonical.encode())
        successors = self.storage.execute(
            tenant_id,
            "SELECT digest FROM ingest_events WHERE tenant_id=? AND supersedes_digest=?",
            (tenant_id, digest)).fetchall()
        return {
            "digest": digest,
            "digest_recomputed_ok": recomputed == digest,
            "receipt": receipt,
            "normalized_event": json.loads(canonical),
            "supersedes": receipt.get("supersedes_digest"),
            "superseded_by": [r["digest"] for r in successors],
            "source_registered": receipt.get("source_id") in self.sources,
        }


# --------------------------------------------------------------------------
# connectors
# --------------------------------------------------------------------------

LANES = ("lane-asia-uswest", "lane-asia-euro", "lane-transatlantic",
         "lane-intra-americas")
DISRUPTION_CLASSES = ("port_congestion", "supplier_insolvency", "weather_closure",
                      "customs_hold")


class SyntheticConnector:
    """Deterministic synthetic source — the labeled fixture data generator.
    Same seed ⇒ same signed envelopes (a fresh keypair is minted per
    connector; register its public key as the source authority)."""

    def __init__(self, *, source_id: str, tenant_id: str, seed: int):
        self.source_id = source_id
        self.tenant_id = tenant_id
        self.seed = seed
        self._private, self.public_key_pem = generate_demo_keypair()
        self.key_id = _pem_key_id(self.public_key_pem)

    def source_registration(self) -> dict[str, Any]:
        return {"public_key_pem": self.public_key_pem,
                "tenant_id": self.tenant_id,
                "authorized_kinds": ["disruption_signal", "registry_task", "correction"],
                "display_name": f"synthetic fixture connector {self.source_id}"}

    def _sign_envelope(self, event: dict[str, Any]) -> dict[str, Any]:
        return {"event": event,
                "signature_b64": base64.b64encode(
                    _sign(_canonical(event), self._private)).decode(),
                "key_id": self.key_id}

    def events(self, count: int, *, start_at: float | None = None,
               batch: str = "0") -> list[dict[str, Any]]:
        rng = random.Random(self.seed)
        base_time = start_at if start_at is not None else time.time() - 3600
        envelopes = []
        for index in range(count):
            event = {
                "contract_version": INGEST_CONTRACT,
                "event_kind": "disruption_signal",
                "source_id": self.source_id,
                "tenant_id": self.tenant_id,
                "occurred_at": base_time + index * 60.0,
                "idempotency_key": f"syn-{self.seed}-{batch}-{index}",
                "payload": {
                    "lane": rng.choice(LANES),
                    "disruption_class": rng.choice(DISRUPTION_CLASSES),
                    "severity": round(rng.uniform(0.05, 0.95), 3),
                    "description": f"synthetic fixture signal #{index} (seed {self.seed})",
                },
            }
            envelopes.append(self._sign_envelope(event))
        return envelopes

    def export_jsonl(self, path: str | Path, count: int) -> Path:
        """Write signed envelopes to a replayable fixture file."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w") as handle:
            for envelope in self.events(count):
                handle.write(json.dumps(envelope, sort_keys=True) + "\n")
        return target


class FileReplayConnector:
    """Replayable file source: JSONL of signed envelopes, or CSV rows that
    the connector itself signs as the registered source authority (raw-row
    provenance recorded in the event payload)."""

    def __init__(self, *, source_id: str, tenant_id: str):
        self.source_id = source_id
        self.tenant_id = tenant_id
        self._private, self.public_key_pem = generate_demo_keypair()
        self.key_id = _pem_key_id(self.public_key_pem)

    def source_registration(self) -> dict[str, Any]:
        return {"public_key_pem": self.public_key_pem,
                "tenant_id": self.tenant_id,
                "authorized_kinds": ["disruption_signal", "registry_task", "correction"],
                "display_name": f"file replay connector {self.source_id}"}

    def iter_jsonl(self, path: str | Path) -> Iterator[dict[str, Any]]:
        for line in Path(path).read_text().splitlines():
            if line.strip():
                yield json.loads(line)

    def iter_csv(self, path: str | Path) -> Iterator[dict[str, Any]]:
        text = Path(path).read_text()
        reader = csv.DictReader(io.StringIO(text))
        for index, row in enumerate(reader):
            raw_row_sha = _sha256(_canonical(row))
            event = {
                "contract_version": INGEST_CONTRACT,
                "event_kind": "disruption_signal",
                "source_id": self.source_id,
                "tenant_id": self.tenant_id,
                "occurred_at": float(row["occurred_at"]),
                "idempotency_key": row.get("idempotency_key") or f"csv-{raw_row_sha[:16]}",
                "payload": {
                    "lane": row["lane"],
                    "disruption_class": row["disruption_class"],
                    "severity": float(row["severity"]),
                    "description": row.get("description", f"csv row {index}"),
                    "raw_row_sha256": raw_row_sha,
                },
            }
            yield {"event": event,
                   "signature_b64": base64.b64encode(
                       _sign(_canonical(event), self._private)).decode(),
                   "key_id": self.key_id}


class HttpWebhookConnector:
    """DISABLED interface for a future authorized HTTP/webhook source.

    To add an authorized customer connector later: (1) register the source
    identity + public key with the pilot's source registry, (2) subclass or
    configure this connector with real transport auth, (3) enable it
    EXPLICITLY in operator configuration, (4) independently verify signed
    delivery end-to-end. Until all four happen, every call fails closed."""

    enabled = False

    def __init__(self, *, source_id: str = "http-webhook-unconfigured"):
        self.source_id = source_id

    def start(self, *_args, **_kwargs):
        raise ConnectorDisabled(
            "HTTP/webhook connector is DISABLED in the pilot reference build "
            "(no authorized source configured). See PILOT_OPERATOR_RUNBOOK.md "
            "for the exact authorization steps.")

    def receive(self, *_args, **_kwargs):
        raise ConnectorDisabled("HTTP/webhook connector is DISABLED (fail closed)")
