"""Pilot smoke — the COMPLETE product loop, end-to-end, over real HTTP.

    AUTHORIZED INGEST → TENANT-BOUND IDENTITY → DURABLE EVIDENCE → DECISION
    → HUMAN REQUEST → INDEPENDENT APPROVAL → SHADOW EXECUTION
    → OUTCOME CAPTURE → REPLAY → EXPORTABLE AUDIT RECEIPT

Runs against a REAL `pilot up` deployment (separate evaluator process,
separate cockpit server process), in a fresh pilot home, with three distinct
dev-issuer identities (analyst / approver / operator). Every step asserts;
any failure exits nonzero. Also exercises backup + restore-check and the
evaluator status probe, then shuts everything down cleanly.

Writes artifacts/pilot/PILOT_SMOKE_RECEIPT.json (machine-readable).
usage: PYTHONPATH=src python scripts/pilot_smoke.py [port]
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eagle_eye.pilot.ops import cmd_down, cmd_setup, cmd_up  # noqa: E402
from eagle_eye.pilot.storage import PilotStorage  # noqa: E402

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("EAGLE_EYE_PILOT_SMOKE_PORT", "8899"))
HOME = ROOT / "artifacts" / "pilot" / "smoke-home"
BASE = f"http://127.0.0.1:{PORT}"

STEPS: list[dict] = []


def step(name: str, ok: bool, detail: str = "") -> None:
    STEPS.append({"step": name, "ok": bool(ok), "detail": detail[:300]})
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail[:120]}")
    if not ok:
        finish(1)


def finish(code: int) -> None:
    receipt = {
        "spec": "eagle-eye-pilot-smoke/6.0",
        "label": "LOCAL_SYNTHETIC_PILOT_SMOKE",
        "port": PORT,
        "steps": STEPS,
        "all_pass": all(s["ok"] for s in STEPS) and code == 0,
        "finished_at": time.time(),
    }
    out = ROOT / "artifacts" / "pilot" / "PILOT_SMOKE_RECEIPT.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, sort_keys=True))
    try:
        cmd_down(HOME)
    except Exception:
        pass
    print("PILOT_SMOKE_PASS" if receipt["all_pass"] else "PILOT_SMOKE_FAIL")
    raise SystemExit(code)


def call(method: str, path: str, *, token: str | None = None,
         body: dict | None = None, expect: int = 200) -> dict:
    request = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            payload = json.loads(resp.read())
            status = resp.status
    except urllib.error.HTTPError as exc:
        payload = json.loads(exc.read() or b"{}")
        status = exc.code
    if status != expect:
        step(f"{method} {path}", False,
             f"expected {expect}, got {status}: {payload}")
    return payload


def main() -> None:
    # fresh home each run: migrations from EMPTY state are part of the gate
    if HOME.exists():
        shutil.rmtree(HOME)
    os.environ["EAGLE_EYE_PILOT_HOME"] = str(HOME)
    os.environ["EAGLE_EYE_PORT"] = str(PORT)

    step("pilot-setup (fresh home, migrations from empty)", cmd_setup(HOME) == 0)
    step("pilot-up (evaluator + cockpit processes)", cmd_up(HOME) == 0)

    status = call("GET", "/api/pilot/status")
    step("status: external execution false + fixture labeling",
         status["external_execution"] is False and status["data_class"] == "FIXTURE"
         and status["adapters"]["all_fail_closed"] is True
         and status["identity"]["development_issuer"]["production"] is False)

    # tenant-bound identities (three distinct principals)
    analyst = call("POST", "/api/pilot/dev-issuer/mint",
                   body={"subject": "smoke-analyst", "roles": ["analyst"]})["token"]
    approver = call("POST", "/api/pilot/dev-issuer/mint",
                    body={"subject": "smoke-approver", "roles": ["approver"]})["token"]
    operator = call("POST", "/api/pilot/dev-issuer/mint",
                    body={"subject": "smoke-operator", "roles": ["operator"]})["token"]
    step("identity: three labeled dev principals minted", True)

    denied = call("GET", "/api/pilot/ingest/events", expect=401)
    step("identity: missing auth is refused", denied.get("state") == "IDENTITY_REQUIRED")

    # AUTHORIZED INGEST (operator runs it; analyst can only read)
    batch = call("POST", "/api/pilot/ingest/synthetic", token=operator,
                 body={"count": 6})
    step("ingest: signed synthetic batch accepted",
         batch["accepted"] == 6 and len(batch["digests"]) == 6)
    forbidden = call("POST", "/api/pilot/ingest/synthetic", token=analyst,
                     body={"count": 1}, expect=403)
    step("authz: analyst may not run ingest", forbidden.get("state") == "PERMISSION_DENIED")

    # DURABLE EVIDENCE + provenance
    digest = batch["digests"][0]
    trace = call("GET", f"/api/pilot/provenance/{digest}", token=analyst)
    step("provenance: raw→normalized trace verifies",
         trace["digest_recomputed_ok"] and trace["source_registered"])

    # DECISION
    decision = call("POST", "/api/pilot/decision", token=analyst,
                    body={"evidence_ids": batch["digests"][:4]})
    step("decision: labeled fixture decision support",
         decision["label"] == "FIXTURE_DECISION_SUPPORT"
         and decision["external_execution"] is False)

    # HUMAN REQUEST → INDEPENDENT APPROVAL (different identity) → SHADOW
    requested = call("POST", "/api/pilot/actions/request", token=analyst,
                     body={"action_id": decision["recommended_action"]["action_id"],
                           "evidence_ids": batch["digests"][:4],
                           "summary": "smoke loop bounded action"})
    rid = requested["request_id"]
    step("request: awaiting independent approval",
         requested["state"] == "AWAITING_INDEPENDENT_APPROVAL")

    self_approve = call("POST", f"/api/pilot/actions/{rid}/approve", token=analyst,
                        expect=403)
    step("authz: requester cannot approve (role separation)",
         self_approve.get("state") == "PERMISSION_DENIED")
    approved = call("POST", f"/api/pilot/actions/{rid}/approve", token=approver)
    step("approval: independent approver approved", approved["state"] == "APPROVED_SHADOW")

    dispatched = call("POST", f"/api/pilot/actions/{rid}/dispatch", token=analyst,
                      body={"idempotency_key": f"smoke-{rid}"})
    step("dispatch: shadow dispatched, external execution false",
         dispatched["state"] == "OUTCOME_PENDING"
         and dispatched["dispatch"]["external_execution"] is False)
    replayed = call("POST", f"/api/pilot/actions/{rid}/dispatch", token=analyst,
                    body={"idempotency_key": f"smoke-{rid}"})
    step("dispatch: idempotent replay returns the same receipt",
         replayed.get("idempotent_replay") is True
         and replayed["dispatch"]["dispatch_id"] == dispatched["dispatch"]["dispatch_id"])

    # OUTCOME CAPTURE
    outcome = call("POST", f"/api/pilot/actions/{rid}/outcome", token=analyst,
                   body={"observed": {"predicted_delay_days": 12.0,
                                      "actual_delay_days": 11.0,
                                      "note": "fixture outcome"}})
    step("outcome: recorded with resolver identity",
         outcome["state"] == "OUTCOME_RECORDED"
         and outcome["outcome"]["resolver_id"] == "smoke-analyst")

    # REPLAY
    replay = call("POST", f"/api/pilot/actions/{rid}/replay", token=analyst)
    step("replay: full decision trail verified",
         replay["verified"] is True and all(replay["checks"].values()))

    # EXPORTABLE AUDIT RECEIPT
    export = call("POST", f"/api/pilot/actions/{rid}/export", token=operator)
    step("export: evidence room stored content-addressed",
         len(export["object_digest"]) == 64 and export["bytes"] > 1000)

    detail = call("GET", f"/api/pilot/actions/{rid}", token=analyst)
    step("lifecycle: REPLAY_VERIFIED with a legal 6-step timeline",
         detail["state"] == "REPLAY_VERIFIED" and len(detail["timeline"]) == 6)

    # evaluator process boundary is live
    evaluator = call("GET", "/api/pilot/evaluator/status", token=analyst)
    step("evaluator: separate process reachable with commitment",
         evaluator["lifecycle"] in ("INITIALIZED", "EVALUATING")
         and len(evaluator["commitment"]) == 64)

    # backup + restore-check through the API and storage layers
    backup = call("POST", "/api/pilot/backup", token=operator)
    result = PilotStorage.restore_check(Path(backup["backup_dir"]))
    step("backup/restore: audit heads reproduced from backup",
         result["all_heads_reproduced"] is True)

    # metrics + health are live and labeled
    metrics = call("GET", "/api/pilot/metrics")
    step("metrics: labeled local telemetry with request timings",
         metrics["label"] == "LOCAL_SYNTHETIC_PILOT_TELEMETRY"
         and metrics["durations"].get("api.request", {}).get("count", 0) > 5)

    finish(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # any crash is an explicit failure
        step(f"unhandled {type(exc).__name__}", False, str(exc))
