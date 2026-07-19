"""Process-isolated sealed evaluator — a separately launched local service.

V5's sealed evaluator is an in-process software boundary (honestly labeled).
V6 moves the PILOT evaluation path to a real OS process boundary:

  orchestrator/candidate process                evaluator process
  ───────────────────────────────               ──────────────────────────────
  EvaluatorClient ──unix socket──▶  EvaluatorService (owns the CSPRNG secret,
    reserve_look ◀─ charge FIRST ──   the sealed suites, and the truth labels)
    run candidate code locally
    submit_result ──predictions──▶    scores vs private truth, settles look

HARD PROPERTIES (each has an executable test):
  - the evaluator secret is minted (CSPRNG) INSIDE the evaluator process and
    is supplied to no one; the client sees only the commitment until a
    post-FINALIZED reveal. Candidate code cannot read it: it lives in a
    different address space.
  - authenticated local protocol: every frame carries a launcher-issued
    client token (constant-time compared); the socket is 0700-dir/0600-file.
  - strict request schema: op whitelist, required fields, size-capped frames;
    malformed frames are refused (and refused ≠ crash).
  - a look is CHARGED DURABLY before any context leaves the evaluator;
    success, candidate exception, timeout, malformed submission, disconnect,
    and client crash ALL consume the look (terminal FAILED/TIMED_OUT/
    REJECTED with a reason; never refunded).
  - evaluator restart cannot refund or duplicate a look: the ledger and the
    lifecycle are durable (SQLite, append-only settle-once triggers); on
    restart, dangling reservations are swept to terminal FAILED
    (reason: abandoned_by_restart) and the spent count is monotone.
  - finalize and reveal are irreversible ACROSS restarts (durable states).
  - logs never contain the secret or truth labels (redaction + test).
  - resource bounds: RLIMIT_AS on the service, per-frame byte cap, and a
    per-reservation deadline after which submission settles TIMED_OUT.

The statistical rule is the SAME precommitted core as V4/V5
(`paired_test_from_diffs`), so process isolation does not fork the decision
mathematics. Claim discipline: this is MECHANICALLY VERIFIED process
isolation on one host — NOT organizational isolation, which remains
NOT ESTABLISHED (see V6_HONEST_REMAINING_WALLS.md).
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import hmac
import json
import os
import secrets
import socket
import socketserver
import time
from pathlib import Path
from typing import Any

from ..prediction_court import build_holdout_suite, suite_manifest
from ..predictors import LogScaleDist
from ..prior_registry import canonical_bytes, sha256_hex
from ..prior_selector import select_prior_tasks, compile_prior_context
from ..sealed_evaluator import commitment_for, paired_test_from_diffs
from ..stats import stable_seed
from .kms import EphemeralKeyProvider
from .observability import REDACTION, bind_context, get_logger, log_event
from .storage import PilotStorage

EVALUATOR_PROTO = "eagle-eye-evaluator-proto/6.0"
SERVICE_VERSION = "pilot-evaluator-service/6.0"
MAX_FRAME_BYTES = 8 * 1024 * 1024
DEFAULT_DEADLINE_S = 60.0
OPS = ("status", "reserve_look", "submit_result", "finalize", "reveal", "health")

_LOG = get_logger("pilot.evaluator")


class EvaluatorUnavailable(RuntimeError):
    """The evaluator service cannot be reached (fail closed, surfaced in UI)."""


class EvaluatorRefused(RuntimeError):
    """The evaluator refused a request (auth, schema, lifecycle, budget…)."""

    def __init__(self, message: str, *, code: str = "REFUSED",
                 look_consumed: bool = False):
        super().__init__(message)
        self.code = code
        self.look_consumed = look_consumed


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


# ---------------------------------------------------------------------------
# server-side state
# ---------------------------------------------------------------------------

class EvaluatorState:
    """Durable evaluator state living ONLY in the evaluator process."""

    def __init__(self, *, state_dir: Path, tenant_id: str, run_id: str,
                 suite_scale: int = 1, max_looks: int = 20,
                 alpha_total: float = 0.05):
        self.state_dir = state_dir
        self.tenant_id = tenant_id
        self.run_id = run_id
        self.suite_scale = suite_scale
        self.max_looks = max_looks
        self.alpha_total = alpha_total
        self.alpha_per_look = alpha_total / max_looks
        state_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(state_dir, 0o700)
        self.store = PilotStorage(state_dir / "evaluator-state.sqlite3")
        self.store.migrate()
        self.store.ensure_tenant(tenant_id, display_name="evaluator-run",
                                 data_class="FIXTURE")
        self.signer = EphemeralKeyProvider()
        self._secret = self._load_or_provision_secret()
        REDACTION.register(self._secret)
        self.commitment = commitment_for(self._secret, "csprng_operator_boundary")
        self._promotion = build_holdout_suite(
            stable_seed("promotion-holdout", self._secret) % (1 << 31),
            scale=suite_scale)
        self._final = build_holdout_suite(
            stable_seed("final-audit-holdout", self._secret) % (1 << 31),
            scale=suite_scale)
        self.suite_commitments = {"promotion": suite_manifest(self._promotion),
                                  "final": suite_manifest(self._final)}
        self._ensure_lifecycle_row()
        self.swept_on_start = self._sweep_dangling("abandoned_by_restart")

    # -- secret custody ---------------------------------------------------------
    def _load_or_provision_secret(self) -> str:
        """CSPRNG secret, minted in THIS process on first start, persisted
        0600 inside the evaluator-owned state dir so lifecycle and reveal
        survive restart. It is never written to any shared location and never
        crosses the socket before a post-FINALIZED reveal."""
        secret_path = self.state_dir / "evaluator-secret.private"
        if secret_path.exists():
            return secret_path.read_text().strip()
        value = secrets.token_hex(32)
        secret_path.write_text(value)
        os.chmod(secret_path, 0o600)
        return value

    # -- lifecycle (durable, monotone) -------------------------------------------
    def _ensure_lifecycle_row(self) -> None:
        row = self.store.execute(
            self.tenant_id,
            "SELECT state FROM evaluator_lifecycle WHERE tenant_id=? AND run_id=?",
            (self.tenant_id, self.run_id)).fetchone()
        if row is None:
            with self.store.transaction() as conn:
                conn.execute(
                    "INSERT INTO evaluator_lifecycle VALUES (?,?,?,?,?,?,?,?)",
                    (self.tenant_id, self.run_id, "INITIALIZED", self.commitment,
                     json.dumps(self.suite_commitments, sort_keys=True),
                     time.time(), None, None))

    def lifecycle(self) -> str:
        row = self.store.execute(
            self.tenant_id,
            "SELECT state FROM evaluator_lifecycle WHERE tenant_id=? AND run_id=?",
            (self.tenant_id, self.run_id)).fetchone()
        return row["state"]

    def _set_lifecycle(self, new_state: str) -> None:
        order = {"INITIALIZED": 0, "EVALUATING": 1, "FINALIZED": 2, "REVEALABLE": 3}
        current = self.lifecycle()
        if order[new_state] < order[current]:
            raise EvaluatorRefused(
                f"lifecycle cannot move backwards ({current} → {new_state})",
                code="LIFECYCLE")
        column = {"FINALIZED": "finalized_at", "REVEALABLE": "revealed_at"}.get(new_state)
        with self.store.transaction() as conn:
            if column:
                conn.execute(
                    f"UPDATE evaluator_lifecycle SET state=?, {column}=? "
                    "WHERE tenant_id=? AND run_id=?",
                    (new_state, time.time(), self.tenant_id, self.run_id))
            else:
                conn.execute(
                    "UPDATE evaluator_lifecycle SET state=? WHERE tenant_id=? AND run_id=?",
                    (new_state, self.tenant_id, self.run_id))

    # -- durable looks ---------------------------------------------------------------
    def looks_spent(self) -> int:
        row = self.store.execute(
            self.tenant_id,
            "SELECT COUNT(*) AS n FROM evaluator_looks WHERE tenant_id=? AND run_id=? "
            "AND kind='promotion'", (self.tenant_id, self.run_id)).fetchone()
        return row["n"]

    def final_audit_used(self) -> bool:
        row = self.store.execute(
            self.tenant_id,
            "SELECT COUNT(*) AS n FROM evaluator_looks WHERE tenant_id=? AND run_id=? "
            "AND kind='final_audit'", (self.tenant_id, self.run_id)).fetchone()
        return row["n"] > 0

    def nonce_seen(self, nonce: str) -> bool:
        row = self.store.execute(
            self.tenant_id,
            "SELECT COUNT(*) AS n FROM evaluator_looks WHERE tenant_id=? AND run_id=? "
            "AND json_extract(charge_row_json, '$.nonce')=?",
            (self.tenant_id, self.run_id, nonce)).fetchone()
        return row["n"] > 0

    def charge(self, *, kind: str, candidate_id: str, snapshot_id: str,
               nonce: str, deadline_s: float) -> dict[str, Any]:
        look_index = self.looks_spent() + 1 if kind == "promotion" else 1
        look_id = f"look-{secrets.token_hex(8)}"
        charge_row = {
            "kind": kind, "look_id": look_id, "look_index": look_index,
            "candidate_id": candidate_id, "snapshot_id": snapshot_id,
            "nonce": nonce, "tenant_id": self.tenant_id, "run_id": self.run_id,
            "charged_at": time.time(), "service": SERVICE_VERSION,
        }
        charge_row["charge_hash"] = sha256_hex(canonical_bytes(charge_row))
        charge_row["signature_b64"] = base64.b64encode(
            self.signer.sign(charge_row["charge_hash"].encode())).decode()
        charge_row["signer_key_id"] = self.signer.key_id()
        with self.store.transaction() as conn:
            conn.execute(
                "INSERT INTO evaluator_looks "
                "(tenant_id, run_id, look_id, kind, look_index, charged_at, deadline, "
                " charge_row_json, terminal_status, result_row_json, settled_at) "
                "VALUES (?,?,?,?,?,?,?,?,NULL,NULL,NULL)",
                (self.tenant_id, self.run_id, look_id, kind, look_index,
                 charge_row["charged_at"], charge_row["charged_at"] + deadline_s,
                 json.dumps(charge_row, sort_keys=True)))
        if self.lifecycle() == "INITIALIZED":
            self._set_lifecycle("EVALUATING")
        self.store.audit_append(
            self.tenant_id, event_type="EVALUATOR_LOOK_CHARGED",
            actor_id="evaluator-service",
            payload={"look_id": look_id, "kind": kind, "look_index": look_index,
                     "candidate_id": candidate_id},
            idempotency_key=f"charge:{look_id}", signer=self.signer)
        return charge_row

    def settle(self, look_id: str, *, terminal_status: str,
               result: dict[str, Any]) -> dict[str, Any]:
        result_row = {
            "look_id": look_id, "terminal_status": terminal_status,
            "settled_at": time.time(), **result,
        }
        result_row["result_hash"] = sha256_hex(canonical_bytes(result_row))
        result_row["signature_b64"] = base64.b64encode(
            self.signer.sign(result_row["result_hash"].encode())).decode()
        with self.store.transaction() as conn:
            conn.execute(
                "UPDATE evaluator_looks SET terminal_status=?, result_row_json=?, "
                "settled_at=? WHERE tenant_id=? AND run_id=? AND look_id=?",
                (terminal_status, json.dumps(result_row, sort_keys=True),
                 result_row["settled_at"], self.tenant_id, self.run_id, look_id))
        self.store.audit_append(
            self.tenant_id, event_type="EVALUATOR_LOOK_SETTLED",
            actor_id="evaluator-service",
            payload={"look_id": look_id, "terminal_status": terminal_status,
                     "reason": result.get("reason")},
            idempotency_key=f"settle:{look_id}", signer=self.signer)
        return result_row

    def open_reservation(self, look_id: str) -> dict[str, Any] | None:
        row = self.store.execute(
            self.tenant_id,
            "SELECT * FROM evaluator_looks WHERE tenant_id=? AND run_id=? AND look_id=?",
            (self.tenant_id, self.run_id, look_id)).fetchone()
        return dict(row) if row else None

    def _sweep_dangling(self, reason: str) -> int:
        """Terminal-settle every unsettled reservation (restart/crash sweep).
        Consumed looks stay consumed — there is no refund path anywhere."""
        rows = self.store.execute(
            self.tenant_id,
            "SELECT look_id FROM evaluator_looks WHERE tenant_id=? AND run_id=? "
            "AND terminal_status IS NULL", (self.tenant_id, self.run_id)).fetchall()
        for row in rows:
            self.settle(row["look_id"], terminal_status="FAILED",
                        result={"reason": reason, "error_class": "Abandoned"})
        return len(rows)

    def sweep_expired(self) -> int:
        rows = self.store.execute(
            self.tenant_id,
            "SELECT look_id FROM evaluator_looks WHERE tenant_id=? AND run_id=? "
            "AND terminal_status IS NULL AND deadline < ?",
            (self.tenant_id, self.run_id, time.time())).fetchall()
        for row in rows:
            self.settle(row["look_id"], terminal_status="TIMED_OUT",
                        result={"reason": "reservation deadline passed",
                                "error_class": "Timeout"})
        return len(rows)

    # -- suites / scoring ---------------------------------------------------------
    def visible_contexts(self, suite_kind: str, config: dict[str, Any]) -> list[dict[str, Any]]:
        """Compile predictor-visible contexts for every case: prior blocks +
        target features. NO truth labels leave this function — a test greps
        the wire payload for the truth vocabulary."""
        suite = self._promotion if suite_kind == "promotion" else self._final
        registry = self._registry_for(suite)
        contexts = []
        for row in suite["cases"]:
            target = row["target"]
            selection = select_prior_tasks(
                registry, target,
                k_max=config.get("selector.k_max", row["k_max"]),
                min_score=config.get("selector.min_score_milli", 4000) / 1000.0)
            compiled = compile_prior_context(selection["included"], target)
            contexts.append({"case_id": target["case_id"],
                             "compiled": copy.deepcopy(compiled)})
        return contexts

    def _registry_for(self, suite: dict[str, Any]) -> dict[str, Any]:
        """Prior-task registry from the suite's own world (the same pattern
        the sealed-evolution driver uses: registry tasks = world tasks)."""
        from ..prior_registry import build_registry
        return build_registry(list(suite["world"]["tasks"]), release="pilot-eval/1")

    def score_submission(self, suite_kind: str,
                         cases: list[dict[str, Any]]) -> dict[str, Any]:
        """Score serialized predictions against PRIVATE truth. Strict: every
        submitted case must exist; distributions must be finite/valid."""
        suite = self._promotion if suite_kind == "promotion" else self._final
        truth_by_case = {row["target"]["case_id"]: row["truth"] for row in suite["cases"]}
        per_case = []
        for item in cases:
            case_id = item.get("case_id")
            if case_id not in truth_by_case:
                raise ValueError(f"unknown case_id {case_id!r} in submission")
            if item.get("abstained"):
                per_case.append({"case_id": case_id, "abstained": True})
                continue
            dist_spec = item.get("dist") or {}
            loc, scale = dist_spec.get("loc"), dist_spec.get("scale")
            df = dist_spec.get("df")
            if not isinstance(loc, (int, float)) or not isinstance(scale, (int, float)) \
                    or isinstance(loc, bool) or isinstance(scale, bool) or scale <= 0:
                raise ValueError(f"invalid distribution for case {case_id!r}")
            dist = LogScaleDist(float(loc), float(scale),
                                float(df) if isinstance(df, (int, float)) and not isinstance(df, bool) else None)
            truth = truth_by_case[case_id]
            y = truth["outcomes"]["wait_incumbent"]["log_final_delay"]
            per_case.append({"case_id": case_id, "abstained": False,
                             "nll": -dist.logpdf(y)})
        return {"per_case": per_case,
                "scored_count": sum(1 for c in per_case if not c["abstained"])}

    def reveal(self) -> dict[str, Any]:
        if self.lifecycle() not in ("FINALIZED", "REVEALABLE"):
            raise EvaluatorRefused(
                f"lifecycle {self.lifecycle()}: reveal refused before FINALIZED",
                code="REVEAL_REFUSED")
        self._set_lifecycle("REVEALABLE")
        return {"evaluator_secret": self._secret,
                "secret_provenance": "csprng_operator_boundary",
                "seed_commitment": self.commitment,
                "suite_commitments": self.suite_commitments,
                "lifecycle_at_reveal": "REVEALABLE"}

    def close(self) -> None:
        self.store.close()


# ---------------------------------------------------------------------------
# the protocol server
# ---------------------------------------------------------------------------

class EvaluatorService:
    """Blocking unix-socket JSON-lines server around EvaluatorState."""

    def __init__(self, *, socket_path: Path, client_token: str,
                 state: EvaluatorState):
        self.socket_path = socket_path
        self.client_token = client_token
        self.state = state
        REDACTION.register(client_token)

    # -- request handling ----------------------------------------------------------
    def handle_frame(self, frame: bytes) -> dict[str, Any]:
        if len(frame) > MAX_FRAME_BYTES:
            return {"ok": False, "code": "FRAME_TOO_LARGE",
                    "error": f"frame exceeds {MAX_FRAME_BYTES} bytes"}
        try:
            request = json.loads(frame.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"ok": False, "code": "MALFORMED", "error": "frame is not valid JSON"}
        if not isinstance(request, dict):
            return {"ok": False, "code": "MALFORMED", "error": "request must be an object"}
        # authenticated local protocol — constant-time token check FIRST
        token = request.get("auth", "")
        if not isinstance(token, str) or not hmac.compare_digest(token, self.client_token):
            return {"ok": False, "code": "UNAUTHENTICATED",
                    "error": "invalid or missing client token"}
        if request.get("spec") != EVALUATOR_PROTO:
            return {"ok": False, "code": "BAD_SPEC",
                    "error": f"spec must be {EVALUATOR_PROTO}"}
        op = request.get("op")
        if op not in OPS:
            return {"ok": False, "code": "UNKNOWN_OP",
                    "error": f"op must be one of {OPS}"}
        bind_context(trace_id=str(request.get("trace_id", "")),
                     run_id=self.state.run_id, tenant_id=self.state.tenant_id)
        try:
            handler = getattr(self, f"_op_{op}")
            response = handler(request)
            response.setdefault("ok", True)
            return response
        except EvaluatorRefused as exc:
            return {"ok": False, "code": exc.code, "error": str(exc),
                    "look_consumed": exc.look_consumed}
        except Exception as exc:  # never crash the service on one request
            log_event(_LOG, "evaluator internal error",
                      error_class=type(exc).__name__)
            return {"ok": False, "code": "INTERNAL", "error": type(exc).__name__}

    # -- ops ---------------------------------------------------------------------------
    def _op_health(self, request: dict[str, Any]) -> dict[str, Any]:
        return {"service": SERVICE_VERSION, "pid": os.getpid(),
                "lifecycle": self.state.lifecycle()}

    def _op_status(self, request: dict[str, Any]) -> dict[str, Any]:
        self.state.sweep_expired()
        return {
            "service": SERVICE_VERSION,
            "lifecycle": self.state.lifecycle(),
            "looks_spent": self.state.looks_spent(),
            "max_looks": self.state.max_looks,
            "alpha_per_look_micro": int(round(self.state.alpha_per_look * 1e6)),
            "alpha_spent_micro": int(round(self.state.looks_spent()
                                           * self.state.alpha_per_look * 1e6)),
            "commitment": self.state.commitment,
            "suite_commitments": self.state.suite_commitments,
            "final_audit_used": self.state.final_audit_used(),
            "swept_on_start": self.state.swept_on_start,
            "signer_key_id": self.state.signer.key_id(),
        }

    def _op_reserve_look(self, request: dict[str, Any]) -> dict[str, Any]:
        for field in ("kind", "candidate_id", "snapshot_id", "nonce",
                      "champion_config", "challenger_config"):
            if field not in request:
                raise EvaluatorRefused(f"missing field {field!r}", code="SCHEMA")
        kind = request["kind"]
        if kind not in ("promotion", "final_audit"):
            raise EvaluatorRefused("kind must be promotion|final_audit", code="SCHEMA")
        if self.state.lifecycle() in ("FINALIZED", "REVEALABLE"):
            raise EvaluatorRefused("lifecycle closed: no further looks",
                                   code="LIFECYCLE")
        self.state.sweep_expired()
        if self.state.nonce_seen(request["nonce"]):
            raise EvaluatorRefused("replayed nonce: one-shot requests only",
                                   code="NONCE_REPLAY")
        if kind == "promotion" and self.state.looks_spent() >= self.state.max_looks:
            raise EvaluatorRefused("access budget exhausted", code="BUDGET")
        if kind == "final_audit" and self.state.final_audit_used():
            raise EvaluatorRefused("final audit holdout is strictly one-shot",
                                   code="FINAL_ONESHOT")
        deadline_s = float(request.get("deadline_s", DEFAULT_DEADLINE_S))
        # CHARGE FIRST — durable, signed, before any context leaves.
        charge = self.state.charge(
            kind=kind, candidate_id=str(request["candidate_id"]),
            snapshot_id=str(request["snapshot_id"]), nonce=str(request["nonce"]),
            deadline_s=deadline_s)
        suite_kind = "promotion" if kind == "promotion" else "final"
        return {
            "look_id": charge["look_id"],
            "look_index": charge["look_index"],
            "charge": charge,
            "deadline": charge["charged_at"] + deadline_s,
            "champion_contexts": self.state.visible_contexts(
                suite_kind, dict(request["champion_config"])),
            "challenger_contexts": self.state.visible_contexts(
                suite_kind, dict(request["challenger_config"])),
        }

    def _op_submit_result(self, request: dict[str, Any]) -> dict[str, Any]:
        look_id = request.get("look_id")
        if not isinstance(look_id, str):
            raise EvaluatorRefused("missing look_id", code="SCHEMA")
        reservation = self.state.open_reservation(look_id)
        if reservation is None:
            raise EvaluatorRefused("unknown look_id", code="UNKNOWN_LOOK")
        if reservation["terminal_status"] is not None:
            raise EvaluatorRefused(
                f"look already settled ({reservation['terminal_status']}); "
                "no re-submission, no refund", code="ALREADY_SETTLED",
                look_consumed=True)
        if time.time() > reservation["deadline"]:
            self.state.settle(look_id, terminal_status="TIMED_OUT",
                              result={"reason": "submission after deadline",
                                      "error_class": "Timeout"})
            raise EvaluatorRefused("deadline passed; look consumed as TIMED_OUT",
                                   code="TIMED_OUT", look_consumed=True)
        suite_kind = "promotion" if reservation["kind"] == "promotion" else "final"
        try:
            champ = self.state.score_submission(
                suite_kind, request.get("champion_cases") or [])
            chall = self.state.score_submission(
                suite_kind, request.get("challenger_cases") or [])
        except (ValueError, TypeError, KeyError) as exc:
            self.state.settle(look_id, terminal_status="REJECTED",
                              result={"reason": f"malformed submission: {exc}",
                                      "error_class": type(exc).__name__})
            raise EvaluatorRefused(f"malformed submission; look consumed ({exc})",
                                   code="REJECTED", look_consumed=True)
        champ_by_case = {c["case_id"]: c for c in champ["per_case"] if not c["abstained"]}
        diffs = [c["nll"] - champ_by_case[c["case_id"]]["nll"]
                 for c in chall["per_case"]
                 if not c["abstained"] and c["case_id"] in champ_by_case]
        statistics = paired_test_from_diffs(diffs, self.state.alpha_per_look)
        statistics["alpha_per_look_micro"] = int(round(self.state.alpha_per_look * 1e6))
        result = self.state.settle(look_id, terminal_status="SUCCEEDED", result={
            "statistics": statistics,
            "champion_scored": champ["scored_count"],
            "challenger_scored": chall["scored_count"],
            "paired_diffs": [round(d, 9) for d in diffs],
        })
        return {"look_id": look_id, "terminal_status": "SUCCEEDED",
                "statistics": statistics, "result_hash": result["result_hash"]}

    def _op_finalize(self, request: dict[str, Any]) -> dict[str, Any]:
        if self.state.lifecycle() in ("FINALIZED", "REVEALABLE"):
            raise EvaluatorRefused("already finalized (irreversible)",
                                   code="LIFECYCLE")
        self.state.sweep_expired()
        self.state._sweep_dangling("open_at_finalize")
        self.state._set_lifecycle("FINALIZED")
        self.state.store.audit_append(
            self.state.tenant_id, event_type="EVALUATOR_FINALIZED",
            actor_id="evaluator-service",
            payload={"looks_spent": self.state.looks_spent()},
            idempotency_key=f"finalize:{self.state.run_id}",
            signer=self.state.signer)
        return {"lifecycle": "FINALIZED", "looks_spent": self.state.looks_spent()}

    def _op_reveal(self, request: dict[str, Any]) -> dict[str, Any]:
        return self.state.reveal()

    # -- serving -------------------------------------------------------------------------
    def serve_forever(self) -> None:  # pragma: no cover — exercised as a real subprocess
        service = self

        class Handler(socketserver.StreamRequestHandler):
            def handle(self):
                try:
                    frame = self.rfile.readline(MAX_FRAME_BYTES + 2)
                    if not frame:
                        return
                    response = service.handle_frame(frame.rstrip(b"\n"))
                    self.wfile.write(json.dumps(response, sort_keys=True).encode() + b"\n")
                except BrokenPipeError:
                    pass  # client vanished; reservations stay charged

        class Server(socketserver.ThreadingUnixStreamServer):
            daemon_threads = True

        socket_dir = self.socket_path.parent
        socket_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        if hasattr(os, "getuid") and socket_dir.stat().st_uid != os.getuid():
            raise PermissionError(
                f"evaluator socket directory is not owned by this user: {socket_dir}")
        os.chmod(socket_dir, 0o700)
        if self.socket_path.exists():
            self.socket_path.unlink()
        with Server(str(self.socket_path), Handler) as server:
            os.chmod(self.socket_path, 0o600)
            log_event(_LOG, "evaluator service listening",
                      socket=str(self.socket_path), pid=os.getpid(),
                      lifecycle=self.state.lifecycle(),
                      swept_on_start=self.state.swept_on_start)
            server.serve_forever()


# ---------------------------------------------------------------------------
# client
# ---------------------------------------------------------------------------

class EvaluatorClient:
    """Orchestrator-side client. Holds ONLY the socket path and client token —
    never the evaluator secret, never truth labels."""

    def __init__(self, socket_path: str | Path, client_token: str,
                 *, timeout_s: float = 30.0):
        self.socket_path = str(socket_path)
        self.client_token = client_token
        self.timeout_s = timeout_s

    def request(self, op: str, **fields: Any) -> dict[str, Any]:
        payload = {"spec": EVALUATOR_PROTO, "op": op, "auth": self.client_token,
                   **fields}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout_s)
                sock.connect(self.socket_path)
                sock.sendall(json.dumps(payload).encode() + b"\n")
                chunks = []
                while True:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    if chunk.endswith(b"\n"):
                        break
        except (ConnectionError, FileNotFoundError, socket.timeout, OSError) as exc:
            raise EvaluatorUnavailable(
                f"evaluator service unreachable at {self.socket_path}: "
                f"{type(exc).__name__}") from exc
        raw = b"".join(chunks)
        if not raw:
            raise EvaluatorUnavailable("evaluator closed the connection without replying")
        response = json.loads(raw.decode())
        if not response.get("ok"):
            raise EvaluatorRefused(response.get("error", "refused"),
                                   code=response.get("code", "REFUSED"),
                                   look_consumed=bool(response.get("look_consumed")))
        return response


# ---------------------------------------------------------------------------
# process entrypoint
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:  # pragma: no cover — subprocess entry
    parser = argparse.ArgumentParser(description="Eagle Eye pilot evaluator service")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--state-dir", required=True)
    parser.add_argument("--token-file", required=True,
                        help="launcher-created 0600 file holding the client token")
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--suite-scale", type=int, default=1)
    parser.add_argument("--max-looks", type=int, default=20)
    parser.add_argument("--rlimit-as-mb", type=int, default=2048)
    args = parser.parse_args(argv)

    try:  # resource bounds on the service itself
        import resource
        limit = args.rlimit_as_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):
        pass  # unavailable on this platform; documented soft dependency

    client_token = Path(args.token_file).read_text().strip()
    state = EvaluatorState(state_dir=Path(args.state_dir), tenant_id=args.tenant,
                           run_id=args.run_id, suite_scale=args.suite_scale,
                           max_looks=args.max_looks)
    service = EvaluatorService(socket_path=Path(args.socket),
                               client_token=client_token, state=state)
    service.serve_forever()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
