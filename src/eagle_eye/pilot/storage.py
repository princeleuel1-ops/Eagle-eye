"""Durable pilot storage — the V6 local reference implementation.

A tenant-bound, transactional, append-only-where-it-matters store backed by
SQLite (stdlib), with explicit schema migrations, transactional idempotency,
backup/restore, and separately persisted audit head commitments.

WHY SQLITE
  This environment ships no PostgreSQL server and no Docker. Per the V6
  mission ("use a local process-backed substitute and preserve the same
  interfaces"), the reference backend is SQLite in WAL mode behind a
  storage API that a PostgreSQL implementation can satisfy 1:1. A
  PostgreSQL configuration shape is provided and FAILS CLOSED when no
  server is reachable — it never pretends. Local storage of any kind is a
  PILOT REFERENCE IMPLEMENTATION, not production infrastructure.

HARD PROPERTIES (each enforced mechanically, each tested):
  - every durable key and query is tenant-scoped; there is no cross-tenant
    query path in this API (methods REQUIRE tenant_id and bind it in SQL)
  - duplicate idempotency keys are rejected transactionally (UNIQUE + the
    surrounding transaction)
  - audit rows can never be updated or deleted (BEFORE UPDATE/DELETE
    triggers RAISE) — append-only is a database property, not a convention
  - the terminal audit length/head commitment is persisted separately from
    the rows (its own append-only table + optional object-store mirror)
  - a settled evaluator look can never be re-settled or refunded (trigger)
  - fixture data is labeled at the tenant level (data_class FIXTURE|PILOT)
    so fixtures cannot be mistaken for customer records
  - backup produces a manifest with content hashes; restore-check proves the
    restored database reproduces the same audit heads
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

STORAGE_SPEC = "eagle-eye-pilot-storage/6.0"
DATA_CLASSES = ("FIXTURE", "PILOT")


class StorageError(RuntimeError):
    """Base error for pilot storage failures (fail closed, never fail quiet)."""


class DuplicateIdempotencyKey(StorageError):
    """A previously used idempotency key was presented again."""


class AppendOnlyViolation(StorageError):
    """An UPDATE/DELETE was attempted against an append-only table."""


class TenantRequired(StorageError):
    """A storage call omitted or blanked the mandatory tenant binding."""


class BackendUnavailable(StorageError):
    """A configured backend (e.g. PostgreSQL) is not actually reachable."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_tenant(tenant_id: str) -> str:
    if not tenant_id or not isinstance(tenant_id, str):
        raise TenantRequired("tenant_id is required on every storage call")
    return tenant_id


# --------------------------------------------------------------------------
# migrations — explicit, ordered, checksummed, applied transactionally
# --------------------------------------------------------------------------

MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "core-tenancy-and-idempotency", """
        CREATE TABLE tenants (
            tenant_id   TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            data_class  TEXT NOT NULL CHECK (data_class IN ('FIXTURE','PILOT')),
            created_at  REAL NOT NULL
        );
        CREATE TABLE idempotency_keys (
            tenant_id  TEXT NOT NULL REFERENCES tenants(tenant_id),
            scope      TEXT NOT NULL,
            idem_key   TEXT NOT NULL,
            created_at REAL NOT NULL,
            PRIMARY KEY (tenant_id, scope, idem_key)
        );
    """),
    (2, "durable-audit-append-only", """
        CREATE TABLE audit_events (
            tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id),
            sequence        INTEGER NOT NULL,
            event_type      TEXT NOT NULL,
            actor_id        TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            previous_hash   TEXT NOT NULL,
            payload_json    TEXT NOT NULL,
            event_hash      TEXT NOT NULL,
            signature_b64   TEXT,
            signer_key_id   TEXT,
            recorded_at     REAL NOT NULL,
            PRIMARY KEY (tenant_id, sequence),
            UNIQUE (tenant_id, idempotency_key)
        );
        CREATE TRIGGER audit_events_no_update BEFORE UPDATE ON audit_events
        BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;
        CREATE TRIGGER audit_events_no_delete BEFORE DELETE ON audit_events
        BEGIN SELECT RAISE(ABORT, 'audit_events is append-only'); END;

        CREATE TABLE audit_head_commitments (
            tenant_id     TEXT NOT NULL REFERENCES tenants(tenant_id),
            length        INTEGER NOT NULL,
            head          TEXT NOT NULL,
            committed_at  REAL NOT NULL,
            signature_b64 TEXT,
            signer_key_id TEXT,
            PRIMARY KEY (tenant_id, length)
        );
        CREATE TRIGGER audit_heads_no_update BEFORE UPDATE ON audit_head_commitments
        BEGIN SELECT RAISE(ABORT, 'audit_head_commitments is append-only'); END;
        CREATE TRIGGER audit_heads_no_delete BEFORE DELETE ON audit_head_commitments
        BEGIN SELECT RAISE(ABORT, 'audit_head_commitments is append-only'); END;
    """),
    (3, "ingestion-contract", """
        CREATE TABLE ingest_events (
            tenant_id        TEXT NOT NULL REFERENCES tenants(tenant_id),
            digest           TEXT NOT NULL,
            source_id        TEXT NOT NULL,
            contract_version TEXT NOT NULL,
            event_kind       TEXT NOT NULL,
            canonical_json   TEXT NOT NULL,
            supersedes_digest TEXT,
            received_at      REAL NOT NULL,
            receipt_json     TEXT NOT NULL,
            PRIMARY KEY (tenant_id, digest)
        );
        CREATE TABLE ingest_quarantine (
            quarantine_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id     TEXT NOT NULL,
            source_id     TEXT,
            raw_excerpt   TEXT NOT NULL,
            reasons_json  TEXT NOT NULL,
            received_at   REAL NOT NULL
        );
    """),
    (4, "shadow-lifecycle", """
        CREATE TABLE action_state (
            tenant_id       TEXT NOT NULL REFERENCES tenants(tenant_id),
            request_id      TEXT NOT NULL,
            action_id       TEXT NOT NULL,
            state           TEXT NOT NULL,
            requester_id    TEXT NOT NULL,
            evidence_digest TEXT NOT NULL,
            request_json    TEXT NOT NULL,
            approval_json   TEXT,
            dispatch_json   TEXT,
            outcome_json    TEXT,
            replay_json     TEXT,
            requested_at    REAL NOT NULL,
            approval_expires_at REAL,
            updated_at      REAL NOT NULL,
            PRIMARY KEY (tenant_id, request_id)
        );
        CREATE TABLE shadow_transitions (
            transition_id  INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_id      TEXT NOT NULL,
            request_id     TEXT NOT NULL,
            from_state     TEXT NOT NULL,
            to_state       TEXT NOT NULL,
            actor_id       TEXT NOT NULL,
            audit_sequence INTEGER NOT NULL,
            at             REAL NOT NULL
        );
        CREATE TRIGGER shadow_transitions_no_update BEFORE UPDATE ON shadow_transitions
        BEGIN SELECT RAISE(ABORT, 'shadow_transitions is append-only'); END;
        CREATE TRIGGER shadow_transitions_no_delete BEFORE DELETE ON shadow_transitions
        BEGIN SELECT RAISE(ABORT, 'shadow_transitions is append-only'); END;
    """),
    (5, "evaluator-durable-looks", """
        CREATE TABLE evaluator_lifecycle (
            tenant_id    TEXT NOT NULL,
            run_id       TEXT NOT NULL,
            state        TEXT NOT NULL CHECK (state IN
                          ('INITIALIZED','EVALUATING','FINALIZED','REVEALABLE')),
            commitment   TEXT NOT NULL,
            suites_json  TEXT NOT NULL,
            created_at   REAL NOT NULL,
            finalized_at REAL,
            revealed_at  REAL,
            PRIMARY KEY (tenant_id, run_id)
        );
        CREATE TABLE evaluator_looks (
            tenant_id       TEXT NOT NULL,
            run_id          TEXT NOT NULL,
            look_id         TEXT NOT NULL,
            kind            TEXT NOT NULL,
            look_index      INTEGER NOT NULL,
            charged_at      REAL NOT NULL,
            deadline        REAL NOT NULL,
            charge_row_json TEXT NOT NULL,
            terminal_status TEXT,
            result_row_json TEXT,
            settled_at      REAL,
            PRIMARY KEY (tenant_id, run_id, look_id)
        );
        CREATE TRIGGER evaluator_looks_no_delete BEFORE DELETE ON evaluator_looks
        BEGIN SELECT RAISE(ABORT, 'evaluator_looks is append-only'); END;
        CREATE TRIGGER evaluator_looks_settle_once BEFORE UPDATE ON evaluator_looks
        WHEN OLD.terminal_status IS NOT NULL
        BEGIN SELECT RAISE(ABORT, 'evaluator look already settled; no refund or re-settle'); END;
        CREATE TRIGGER evaluator_looks_charge_immutable BEFORE UPDATE ON evaluator_looks
        WHEN NEW.charge_row_json != OLD.charge_row_json
             OR NEW.look_index != OLD.look_index
             OR NEW.charged_at != OLD.charged_at
        BEGIN SELECT RAISE(ABORT, 'charge fields are immutable'); END;
    """),
]


def migration_plan() -> list[dict[str, Any]]:
    """Machine-readable migration inventory (version, name, checksum)."""
    return [{"version": v, "name": n, "checksum": _sha256(sql.encode())}
            for v, n, sql in MIGRATIONS]


# --------------------------------------------------------------------------
# the SQLite reference backend
# --------------------------------------------------------------------------

class PilotStorage:
    """Tenant-bound durable storage. One instance per database file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # One shared connection, serialized across threads: the pilot server
        # handles each request on a worker thread. sqlite3 in serialized mode
        # tolerates the sharing; the RLock makes our multi-statement
        # transactions (e.g. audit SELECT-then-INSERT) atomic at THIS layer.
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._lock = threading.RLock()
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA synchronous=FULL")

    # -- lifecycle ----------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PilotStorage":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- migrations ----------------------------------------------------------
    def migrate(self) -> dict[str, Any]:
        """Apply all pending migrations transactionally, from any state
        (including empty). Records name+checksum per applied version; refuses
        to run if a recorded checksum no longer matches the code (drift)."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    INTEGER PRIMARY KEY,
                name       TEXT NOT NULL,
                checksum   TEXT NOT NULL,
                applied_at REAL NOT NULL
            )""")
        applied = {row["version"]: row for row in
                   self._conn.execute("SELECT * FROM schema_migrations")}
        newly = []
        for version, name, sql in MIGRATIONS:
            checksum = _sha256(sql.encode())
            if version in applied:
                if applied[version]["checksum"] != checksum:
                    raise StorageError(
                        f"migration {version} ({name}) drifted from the applied "
                        "checksum — refusing to continue (forward-recovery: write a NEW "
                        "migration; never edit an applied one)")
                continue
            with self._lock, self._conn:
                self._conn.executescript(sql)
                self._conn.execute(
                    "INSERT INTO schema_migrations VALUES (?,?,?,?)",
                    (version, name, checksum, time.time()))
            newly.append({"version": version, "name": name})
        return {"spec": STORAGE_SPEC, "applied_now": newly,
                "total_applied": len(MIGRATIONS),
                "schema_version": MIGRATIONS[-1][0]}

    def migration_status(self) -> list[dict[str, Any]]:
        try:
            rows = self._conn.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version")
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    # -- tenants --------------------------------------------------------------
    def ensure_tenant(self, tenant_id: str, *, display_name: str,
                      data_class: str) -> dict[str, Any]:
        _require_tenant(tenant_id)
        if data_class not in DATA_CLASSES:
            raise StorageError(f"data_class must be one of {DATA_CLASSES}")
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO tenants VALUES (?,?,?,?)",
                (tenant_id, display_name, data_class, time.time()))
        row = self._conn.execute(
            "SELECT * FROM tenants WHERE tenant_id=?", (tenant_id,)).fetchone()
        return dict(row)

    def tenant(self, tenant_id: str) -> dict[str, Any] | None:
        _require_tenant(tenant_id)
        row = self._conn.execute(
            "SELECT * FROM tenants WHERE tenant_id=?", (tenant_id,)).fetchone()
        return dict(row) if row else None

    # -- idempotency ------------------------------------------------------------
    def claim_idempotency(self, tenant_id: str, *, scope: str, key: str) -> None:
        """Transactionally claim (tenant, scope, key). Raises
        DuplicateIdempotencyKey on any reuse — the caller's surrounding
        transaction therefore aborts atomically."""
        _require_tenant(tenant_id)
        if not scope or not key:
            raise StorageError("idempotency scope and key are required")
        try:
            with self._lock, self._conn:
                self._conn.execute(
                    "INSERT INTO idempotency_keys VALUES (?,?,?,?)",
                    (tenant_id, scope, key, time.time()))
        except sqlite3.IntegrityError as exc:
            raise DuplicateIdempotencyKey(
                f"idempotency key already used in scope {scope!r}") from exc

    # -- durable audit ------------------------------------------------------------
    def audit_append(self, tenant_id: str, *, event_type: str, actor_id: str,
                     payload: dict[str, Any], idempotency_key: str,
                     signer=None) -> dict[str, Any]:
        """Append one audit event with hash-linking identical to
        eagle_eye.audit (same canonical body, same event_hash rule), so the
        in-memory verifier `eagle_eye.audit.verify_chain` verifies rows loaded
        back from this table without translation. Optionally signs the event
        hash with a pilot KeyProvider."""
        _require_tenant(tenant_id)
        if not event_type or not actor_id or not idempotency_key:
            raise StorageError("event type, actor, and idempotency key are required")
        with self._lock, self._conn:
            row = self._conn.execute(
                "SELECT sequence, event_hash FROM audit_events WHERE tenant_id=? "
                "ORDER BY sequence DESC LIMIT 1", (tenant_id,)).fetchone()
            sequence = (row["sequence"] + 1) if row else 1
            previous = row["event_hash"] if row else "0" * 64
            event = {
                "sequence": sequence,
                "tenant_id": tenant_id,
                "event_type": event_type,
                "actor_id": actor_id,
                "idempotency_key": idempotency_key,
                "previous_hash": previous,
                "payload": payload,
            }
            event_hash = _sha256(_canonical(event))
            event["event_hash"] = event_hash
            signature_b64 = signer_key_id = None
            if signer is not None:
                import base64
                signature_b64 = base64.b64encode(
                    signer.sign(event_hash.encode())).decode()
                signer_key_id = signer.key_id()
            try:
                self._conn.execute(
                    "INSERT INTO audit_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (tenant_id, sequence, event_type, actor_id, idempotency_key,
                     previous, json.dumps(payload, sort_keys=True), event_hash,
                     signature_b64, signer_key_id, time.time()))
            except sqlite3.IntegrityError as exc:
                raise DuplicateIdempotencyKey(
                    "audit idempotency key already used") from exc
        return event

    def audit_events(self, tenant_id: str) -> list[dict[str, Any]]:
        _require_tenant(tenant_id)
        rows = self._conn.execute(
            "SELECT * FROM audit_events WHERE tenant_id=? ORDER BY sequence",
            (tenant_id,))
        out = []
        for r in rows:
            out.append({
                "sequence": r["sequence"], "tenant_id": r["tenant_id"],
                "event_type": r["event_type"], "actor_id": r["actor_id"],
                "idempotency_key": r["idempotency_key"],
                "previous_hash": r["previous_hash"],
                "payload": json.loads(r["payload_json"]),
                "event_hash": r["event_hash"],
            })
        return out

    def audit_head(self, tenant_id: str) -> tuple[int, str]:
        _require_tenant(tenant_id)
        row = self._conn.execute(
            "SELECT sequence, event_hash FROM audit_events WHERE tenant_id=? "
            "ORDER BY sequence DESC LIMIT 1", (tenant_id,)).fetchone()
        return (row["sequence"], row["event_hash"]) if row else (0, "0" * 64)

    def commit_audit_head(self, tenant_id: str, *, signer=None) -> dict[str, Any]:
        """Persist the terminal audit length/head commitment SEPARATELY from
        the rows (its own append-only table). Truncation of audit_events is
        detectable because the commitment outlives the rows."""
        _require_tenant(tenant_id)
        length, head = self.audit_head(tenant_id)
        signature_b64 = signer_key_id = None
        if signer is not None:
            import base64
            body = _canonical({"tenant_id": tenant_id, "length": length, "head": head})
            signature_b64 = base64.b64encode(signer.sign(body)).decode()
            signer_key_id = signer.key_id()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO audit_head_commitments VALUES (?,?,?,?,?,?)",
                (tenant_id, length, head, time.time(), signature_b64, signer_key_id))
        return {"tenant_id": tenant_id, "length": length, "head": head,
                "signer_key_id": signer_key_id, "signature_b64": signature_b64}

    def latest_head_commitment(self, tenant_id: str) -> dict[str, Any] | None:
        _require_tenant(tenant_id)
        row = self._conn.execute(
            "SELECT * FROM audit_head_commitments WHERE tenant_id=? "
            "ORDER BY length DESC LIMIT 1", (tenant_id,)).fetchone()
        return dict(row) if row else None

    # -- raw, tenant-scoped table access for the domain layers -------------------
    def execute(self, tenant_id: str, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Escape hatch for domain modules in THIS package. Refuses any SQL
        that does not bind tenant_id — the no-cross-tenant-query-path rule is
        enforced at the API boundary, not by convention."""
        _require_tenant(tenant_id)
        lowered = " ".join(sql.lower().split())
        if "tenant_id" not in lowered:
            raise TenantRequired("SQL must bind tenant_id explicitly")
        if tenant_id not in params:
            raise TenantRequired("params must include the tenant_id binding")
        with self._lock:
            return self._conn.execute(sql, params)

    @contextmanager
    def transaction(self):
        with self._lock:
            with self._conn:
                yield self._conn

    # -- backup / restore ----------------------------------------------------------
    def backup(self, dest_dir: str | Path, *, object_store_dir: str | Path | None = None,
               signer=None) -> dict[str, Any]:
        """Consistent online backup via the SQLite backup API + optional object
        store copy + a hash manifest including current audit head commitments
        for every tenant."""
        dest = Path(dest_dir)
        dest.mkdir(parents=True, exist_ok=True)
        db_path = dest / "pilot.sqlite3"
        target = sqlite3.connect(str(db_path))
        with self._lock, target:
            self._conn.backup(target)
        target.close()
        heads = {}
        for row in self._conn.execute("SELECT tenant_id FROM tenants"):
            tenant_id = row["tenant_id"]
            length, head = self.audit_head(tenant_id)
            heads[tenant_id] = {"length": length, "head": head}
        objects_copied = 0
        if object_store_dir and Path(object_store_dir).exists():
            shutil.copytree(object_store_dir, dest / "objects", dirs_exist_ok=True)
            objects_copied = sum(1 for p in (dest / "objects").rglob("*") if p.is_file())
        manifest = {
            "spec": "eagle-eye-pilot-backup/6.0",
            "created_at": time.time(),
            "db_sha256": _sha256(db_path.read_bytes()),
            "db_bytes": db_path.stat().st_size,
            "audit_heads": heads,
            "objects_copied": objects_copied,
            "migrations": self.migration_status(),
        }
        if signer is not None:
            import base64
            manifest["manifest_signature_b64"] = base64.b64encode(
                signer.sign(_canonical({k: v for k, v in manifest.items()
                                        if k != "manifest_signature_b64"}))).decode()
            manifest["signer_key_id"] = signer.key_id()
        (dest / "BACKUP_MANIFEST.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True))
        return manifest

    @staticmethod
    def restore_check(backup_dir: str | Path) -> dict[str, Any]:
        """Restore the backup into a scratch copy and PROVE the restored
        database reproduces the manifest's audit heads by recomputing every
        tenant chain with eagle_eye.audit.verify_chain. Fails closed on any
        mismatch or corruption."""
        from eagle_eye.audit import verify_chain
        backup = Path(backup_dir)
        manifest = json.loads((backup / "BACKUP_MANIFEST.json").read_text())
        db_file = backup / "pilot.sqlite3"
        actual_sha = _sha256(db_file.read_bytes())
        if actual_sha != manifest["db_sha256"]:
            raise StorageError(
                f"backup db hash mismatch: manifest {manifest['db_sha256'][:12]} "
                f"vs bytes {actual_sha[:12]} — backup is corrupted")
        scratch = backup / "restore-scratch.sqlite3"
        shutil.copy2(db_file, scratch)
        store = PilotStorage(scratch)
        results = {}
        try:
            for tenant_id, expected in manifest["audit_heads"].items():
                events = store.audit_events(tenant_id)
                if expected["length"] == 0:
                    results[tenant_id] = {"length": 0, "verified": True}
                    continue
                verdict = verify_chain(
                    events, expected_tenant=tenant_id,
                    expected_head=expected["head"],
                    expected_length=expected["length"])
                results[tenant_id] = verdict
        finally:
            store.close()
            scratch.unlink(missing_ok=True)
        return {"spec": "eagle-eye-pilot-restore-check/6.0",
                "db_sha256": actual_sha,
                "tenants": results,
                "all_heads_reproduced": all(v.get("verified") for v in results.values())}


# --------------------------------------------------------------------------
# PostgreSQL configuration shape — fail-closed unless genuinely reachable
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PostgresConfig:
    """Configuration shape for a real PostgreSQL pilot deployment. This
    reference environment ships no server: connect() FAILS CLOSED unless a
    DSN is configured AND a driver is importable AND the server answers.
    A configured interface is not deployed infrastructure."""
    dsn_env_var: str = "EAGLE_EYE_PILOT_POSTGRES_DSN"

    def connect(self):
        dsn = os.environ.get(self.dsn_env_var, "")
        if not dsn:
            raise BackendUnavailable(
                f"PostgreSQL backend disabled: {self.dsn_env_var} is not set. "
                "The supported local pilot reference backend is SQLite "
                "(PilotStorage). NOT ESTABLISHED: production database.")
        try:
            import psycopg  # type: ignore
        except ImportError as exc:
            raise BackendUnavailable(
                "PostgreSQL backend disabled: no psycopg driver in the audited "
                "dependency lock. Wire it in a real pilot, then re-verify.") from exc
        return psycopg.connect(dsn)  # pragma: no cover — needs a live server
