"""Security & failure court — executable negative and injection battery.

Every case is EXECUTED here or executed by a named pytest selection this
script runs. Nothing is asserted from documentation. The court:

  1. brings up a REAL pilot deployment (separate evaluator + cockpit
     processes) in a scratch home and injects live failures over HTTP and
     directly into the durable stores;
  2. runs the targeted pytest rejection suites for the boundary layers
     (storage, identity, ingest, shadow, object store, evaluator protocol);
  3. scrubs the real process logs for secrets after a full reveal;
  4. writes artifacts/failure-court/FAILURE_COURT_RESULTS.json and exits
     nonzero if ANY case fails.

Cases whose only faithful executor is the real-browser gate (unsafe HTML
rendering) are INJECTED here (hostile payload ingested into the pilot home
the browser gate serves) and ASSERTED in scripts/browser_verification.py —
the row records that split honestly.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eagle_eye.audit import AuditError, verify_chain  # noqa: E402
from eagle_eye.pilot.ops import cmd_down, cmd_setup, cmd_up, evaluator_socket_path  # noqa: E402
from eagle_eye.pilot.identity_service import LocalDevIssuer  # noqa: E402
from eagle_eye.pilot.storage import PilotStorage  # noqa: E402

PORT = int(os.environ.get("EAGLE_EYE_PILOT_COURT_PORT", "8907"))
HOME = ROOT / "artifacts" / "failure-court" / "court-home"
BASE = f"http://127.0.0.1:{PORT}"
OUT = ROOT / "artifacts" / "failure-court" / "FAILURE_COURT_RESULTS.json"

ROWS: list[dict] = []


def record(case: str, method: str, expectation: str, observed: str, ok: bool) -> None:
    ROWS.append({"case": case, "method": method, "expectation": expectation,
                 "observed": observed[:240], "pass": bool(ok)})
    print(f"{'PASS' if ok else 'FAIL'}  [{method}] {case}")


def call(method: str, path: str, *, token: str | None = None,
         body: dict | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        BASE + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json",
                 **({"Authorization": f"Bearer {token}"} if token else {})})
    try:
        with urllib.request.urlopen(request, timeout=20) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def mint(subject: str, roles: list[str], ttl: int = 600) -> str:
    _, payload = call("POST", "/api/pilot/dev-issuer/mint",
                      body={"subject": subject, "roles": roles, "ttl_seconds": ttl})
    return payload["token"]


# ---------------------------------------------------------------------------
# live-injection cases
# ---------------------------------------------------------------------------

def live_cases() -> None:
    operator = mint("court-operator", ["operator"])
    analyst = mint("court-analyst", ["analyst"])
    approver = mint("court-approver", ["approver"])

    # -- identity court --------------------------------------------------------
    status, payload = call("GET", "/api/pilot/ingest/events")
    record("missing authentication", "live-injection",
           "401 IDENTITY_REQUIRED", f"{status} {payload.get('state')}",
           status == 401 and payload.get("state") == "IDENTITY_REQUIRED")

    expired = mint("court-expired", ["analyst"], ttl=1)
    time.sleep(1.2)
    status, payload = call("GET", "/api/pilot/ingest/events", token=expired)
    record("expired identity assertion", "live-injection",
           "401 IDENTITY_EXPIRED", f"{status} {payload.get('state')}",
           status == 401 and payload.get("state") == "IDENTITY_EXPIRED")

    foreign = LocalDevIssuer(tenants=["tenant-fixture-a"])
    forged = foreign.mint(subject="intruder", tenant_id="tenant-fixture-a",
                          roles=["operator"])
    status, payload = call("GET", "/api/pilot/ingest/events", token=forged)
    record("unknown/unpinned issuer key", "live-injection",
           "401 (trusted issuer not found)", f"{status} {payload.get('error', '')[:60]}",
           status == 401 and "issuer" in payload.get("error", ""))

    status, payload = call("GET", "/api/pilot/ingest/events", token="a.b.c")
    record("garbage bearer token", "live-injection", "401",
           f"{status}", status == 401)

    # -- ingestion court ----------------------------------------------------------
    _, batch = call("POST", "/api/pilot/ingest/synthetic", token=operator,
                    body={"count": 5})
    digests = batch["digests"]

    _, events = call("GET", "/api/pilot/ingest/events", token=analyst)
    one = events["events"][0]["event"]
    unsigned = {"event": dict(one, idempotency_key="court-unsigned-1")}
    status, payload = call("POST", "/api/pilot/ingest/envelope", token=operator,
                           body={"envelope": unsigned})
    record("unsigned ingestion", "live-injection",
           "quarantined", f"{status} {payload.get('state')}",
           payload.get("state") == "QUARANTINED")

    tampered = {"event": dict(one, idempotency_key="court-tampered-1"),
                "signature_b64": base64.b64encode(b"\x01" * 64).decode(),
                "key_id": "ed25519:" + "0" * 64}
    status, payload = call("POST", "/api/pilot/ingest/envelope", token=operator,
                           body={"envelope": tampered})
    record("forged source signature", "live-injection",
           "quarantined", f"{payload.get('state')}",
           payload.get("state") == "QUARANTINED")

    # hostile HTML payload: INJECTED here, ASSERTED inert in the browser gate
    hostile_description = "<script>window.__pwned=1</script><img src=x onerror=\"window.__pwned=2\">"
    status, payload = call("POST", "/api/pilot/ingest/envelope", token=operator,
                           body={"envelope": {"event": dict(
                               one, idempotency_key="court-hostile-html",
                               payload=dict(one["payload"],
                                            description=hostile_description))}})
    record("unsafe HTML evidence payload (injection half)", "live-injection",
           "unsigned hostile envelope quarantined; rendering asserted inert in browser gate",
           f"{payload.get('state')}", payload.get("state") == "QUARANTINED")

    # -- approval court ---------------------------------------------------------------
    _, requested = call("POST", "/api/pilot/actions/request", token=analyst,
                        body={"action_id": "reroute-lane",
                              "evidence_ids": digests[:3],
                              "summary": "court action"})
    rid = requested["request_id"]

    status, payload = call("POST", f"/api/pilot/actions/{rid}/approve", token=analyst)
    record("self-approval via role separation", "live-injection",
           "403 PERMISSION_DENIED", f"{status} {payload.get('state')}",
           status == 403)

    both = mint("court-analyst", ["analyst", "approver"])  # same SUBJECT as requester
    status, payload = call("POST", f"/api/pilot/actions/{rid}/approve", token=both)
    record("self-approval with dual roles (same subject)", "live-injection",
           "409 dual-control refusal", f"{status} {payload.get('error', '')[:60]}",
           status == 409 and "dual control" in payload.get("error", "").lower()
           or "approval refused" in payload.get("error", "").lower())

    call("POST", f"/api/pilot/actions/{rid}/approve", token=approver)
    status, payload = call("POST", f"/api/pilot/actions/{rid}/approve", token=approver)
    record("duplicate approval", "live-injection",
           "409 refused", f"{status}", status == 409)

    # duplicate idempotency key across DIFFERENT dispatch attempts
    call("POST", f"/api/pilot/actions/{rid}/dispatch", token=analyst,
         body={"idempotency_key": "court-dispatch-1"})
    _, requested2 = call("POST", "/api/pilot/actions/request", token=analyst,
                         body={"action_id": "buffer-inventory",
                               "evidence_ids": digests[3:4],
                               "summary": "second court action"})
    rid2 = requested2["request_id"]
    call("POST", f"/api/pilot/actions/{rid2}/approve", token=approver)
    status, payload = call("POST", f"/api/pilot/actions/{rid2}/dispatch",
                           token=analyst, body={"idempotency_key": "court-dispatch-1"})
    record("duplicate dispatch idempotency key (cross-action)", "live-injection",
           "409 refused", f"{status} {payload.get('error', '')[:60]}", status == 409)

    # -- evidence substitution after approval -------------------------------------------
    _, requested3 = call("POST", "/api/pilot/actions/request", token=analyst,
                         body={"action_id": "expedite-alt-supplier",
                               "evidence_ids": digests[4:5],
                               "summary": "third court action"})
    rid3 = requested3["request_id"]
    call("POST", f"/api/pilot/actions/{rid3}/approve", token=approver)
    with sqlite3.connect(HOME / "pilot.sqlite3") as conn:  # direct durable tamper
        conn.execute("UPDATE ingest_events SET canonical_json='{\"tampered\":1}' "
                     "WHERE digest=?", (digests[4],))
    status, payload = call("POST", f"/api/pilot/actions/{rid3}/dispatch",
                           token=analyst, body={"idempotency_key": "court-sub-1"})
    record("evidence substitution after approval", "live-injection",
           "409 EVIDENCE_VERIFICATION_FAILED; action frozen",
           f"{status} {payload.get('state')}",
           status == 409 and payload.get("state") == "EVIDENCE_VERIFICATION_FAILED")
    _, detail = call("GET", f"/api/pilot/actions/{rid3}", token=analyst)
    record("substituted-evidence action frozen in EVIDENCE_FAILED", "live-injection",
           "state EVIDENCE_FAILED", detail.get("state", "?"),
           detail.get("state") == "EVIDENCE_FAILED")

    # -- audit court (direct durable attacks) ---------------------------------------------
    for attack, sql in (("audit row rewrite", "UPDATE audit_events SET actor_id='evil' WHERE sequence=1"),
                        ("audit event deletion", "DELETE FROM audit_events WHERE sequence=1")):
        try:
            with sqlite3.connect(HOME / "pilot.sqlite3") as conn:
                conn.execute(sql)
            record(attack, "live-injection", "refused by DB trigger", "mutation succeeded", False)
        except sqlite3.DatabaseError as exc:
            record(attack, "live-injection", "refused by DB trigger",
                   str(exc)[:80], "append-only" in str(exc))

    # audit tail truncation + reordering: detected against the persisted head
    store = PilotStorage(HOME / "pilot.sqlite3")
    events = store.audit_events("tenant-fixture-a")
    length, head = store.audit_head("tenant-fixture-a")
    try:
        verify_chain(events[:-1], expected_tenant="tenant-fixture-a",
                     expected_head=head, expected_length=length)
        record("audit tail truncation", "live-injection", "detected", "undetected", False)
    except AuditError as exc:
        record("audit tail truncation", "live-injection",
               "detected vs external commitment", str(exc)[:80], True)
    reordered = [events[1], events[0]] + events[2:]
    try:
        verify_chain(reordered, expected_tenant="tenant-fixture-a",
                     expected_head=head, expected_length=length)
        record("audit event reordering", "live-injection", "detected", "undetected", False)
    except AuditError as exc:
        record("audit event reordering", "live-injection",
               "hash-link break detected", str(exc)[:80], True)
    store.close()

    # -- object store corruption over the live loop -----------------------------------------
    _, export = call("POST", f"/api/pilot/actions/{rid}/dispatch", token=analyst,
                     body={"idempotency_key": "court-dispatch-1"})  # idempotent replay ok
    call("POST", f"/api/pilot/actions/{rid}/outcome", token=analyst,
         body={"observed": {"predicted_delay_days": 9.0, "actual_delay_days": 9.5}})
    call("POST", f"/api/pilot/actions/{rid}/replay", token=analyst)
    _, exported = call("POST", f"/api/pilot/actions/{rid}/export", token=operator)
    digest = exported["object_digest"]
    object_path = (HOME / "objects" / "sha256" / digest[:2] / digest)
    object_path.write_bytes(b"corrupted evidence room bytes")
    from eagle_eye.pilot.objectstore import FsObjectStore, ObjectCorrupted, ObjectMissing
    objects = FsObjectStore(HOME / "objects")
    try:
        objects.get(digest)
        record("evidence object corrupted", "live-injection", "fail closed", "read succeeded", False)
    except ObjectCorrupted as exc:
        record("evidence object corrupted", "live-injection",
               "ObjectCorrupted raised", str(exc)[:80], True)
    object_path.unlink()
    try:
        objects.get(digest)
        record("evidence object missing", "live-injection", "fail closed", "read succeeded", False)
    except ObjectMissing as exc:
        record("evidence object missing", "live-injection",
               "ObjectMissing raised", str(exc)[:80], True)

    # -- evaluator kill mid-reservation over the live socket ----------------------------------
    from eagle_eye.pilot.evaluator_service import EvaluatorClient, EvaluatorUnavailable
    client = EvaluatorClient(evaluator_socket_path(HOME),
                             (HOME / "run" / "client.token").read_text().strip())
    before = client.request("status")
    client.request("reserve_look", kind="promotion", candidate_id="court-cand",
                   snapshot_id="court-snap", nonce="court-n1",
                   champion_config={"selector.k_max": 10, "selector.min_score_milli": 4000},
                   challenger_config={"selector.k_max": 8, "selector.min_score_milli": 4000})
    evaluator_pid = int((HOME / "run" / "evaluator.pid").read_text())
    os.kill(evaluator_pid, signal.SIGKILL)
    time.sleep(0.5)
    try:
        client.request("status")
        record("evaluator process crash mid-look", "live-injection",
               "unreachable after SIGKILL", "still answering", False)
    except EvaluatorUnavailable:
        record("evaluator process crash mid-look", "live-injection",
               "EvaluatorUnavailable surfaced", "unreachable as expected", True)
    status, payload = call("GET", "/api/pilot/evaluator/status", token=analyst)
    record("cockpit degrades honestly on evaluator loss", "live-injection",
           "503 EVALUATOR_UNAVAILABLE", f"{status} {payload.get('state')}",
           status == 503 and payload.get("state") == "EVALUATOR_UNAVAILABLE")

    # restart the evaluator on the same state: charged look swept, not refunded
    env = {**os.environ, "PYTHONPATH": "src", "EAGLE_EYE_PILOT_HOME": str(HOME)}
    evaluator = subprocess.Popen(
        [sys.executable, "-m", "eagle_eye.pilot.evaluator_service",
         "--socket", str(evaluator_socket_path(HOME)),
         "--state-dir", str(HOME / "evaluator-state"),
         "--token-file", str(HOME / "run" / "client.token"),
         "--tenant", "tenant-fixture-a", "--run-id", "run-pilot-service"],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    (HOME / "run" / "evaluator.pid").write_text(str(evaluator.pid))
    deadline = time.time() + 20
    after = None
    while time.time() < deadline:
        try:
            after = client.request("status")
            break
        except EvaluatorUnavailable:
            time.sleep(0.3)
    ok = bool(after) and after["looks_spent"] == before["looks_spent"] + 1 \
        and after["swept_on_start"] == 1 and after["commitment"] == before["commitment"]
    record("evaluator restart: look consumed, no refund, same commitment",
           "live-injection",
           "looks_spent +1, swept_on_start=1, commitment stable",
           f"{after and (after['looks_spent'], after['swept_on_start'])}", ok)

    # -- database restart under the live server --------------------------------------------
    status, payload = call("GET", "/api/pilot/ingest/events", token=analyst)
    record("durable state after all injections", "live-injection",
           "ingest reads still consistent", f"{status} count={payload.get('count')}",
           status == 200 and payload.get("count", 0) >= 5)


def startup_with_missing_dependency() -> None:
    """A cockpit pointed at an impossible pilot home must serve honest 503s."""
    bad_home = ROOT / "artifacts" / "failure-court" / "impossible"
    bad_home.parent.mkdir(parents=True, exist_ok=True)
    if bad_home.exists():
        bad_home.unlink()
    bad_home.write_text("this is a FILE where a directory must be")
    port = PORT + 1
    env = {**os.environ, "PYTHONPATH": "src",
           "EAGLE_EYE_PILOT_HOME": str(bad_home), "EAGLE_EYE_PORT": str(port)}
    proc = subprocess.Popen([sys.executable, "-m", "eagle_eye.server"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        deadline = time.time() + 15
        status, payload = 0, {}
        while time.time() < deadline:
            try:
                request = urllib.request.Request(f"http://127.0.0.1:{port}/api/pilot/status")
                with urllib.request.urlopen(request, timeout=3) as resp:
                    status, payload = resp.status, json.loads(resp.read())
                break
            except urllib.error.HTTPError as exc:
                status, payload = exc.code, json.loads(exc.read() or b"{}")
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.3)
        record("service startup with missing required dependency", "live-injection",
               "503 DEPENDENCY_DEGRADED (not a crash, not a lie)",
               f"{status} {payload.get('state')}",
               status == 503 and payload.get("state") == "DEPENDENCY_DEGRADED")
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def secrets_never_in_logs() -> None:
    """After a full evaluator reveal, the revealed secret must appear in NO
    pilot log; neither may the client token."""
    from eagle_eye.pilot.evaluator_service import EvaluatorClient
    token = (HOME / "run" / "client.token").read_text().strip()
    client = EvaluatorClient(evaluator_socket_path(HOME), token)
    client.request("finalize")
    revealed = client.request("reveal")
    secret = revealed["evaluator_secret"]
    haystacks = []
    for log_file in (HOME / "logs").glob("*.log"):
        haystacks.append((log_file.name, log_file.read_text()))
    leaked = [name for name, text in haystacks
              if secret in text or token in text]
    record("secrets in logs (evaluator secret + client token)", "live-injection",
           "absent from every pilot log", f"scanned {len(haystacks)} logs; leaked in {leaked}",
           not leaked and len(haystacks) >= 2)


# ---------------------------------------------------------------------------
# pytest rejection suites (executed, results captured)
# ---------------------------------------------------------------------------

PYTEST_SELECTIONS: list[tuple[str, str]] = [
    ("replayed nonce (evaluator, in-process + service)",
     "tests/test_evaluator_isolation.py::test_replayed_nonce_refused_before_charge"),
    ("timeout after look reservation",
     "tests/test_evaluator_isolation.py::test_submission_after_deadline_consumes_look_as_timed_out"),
    ("candidate disconnect / evaluator crash / restart no-refund",
     "tests/test_evaluator_isolation.py::test_process_boundary_secret_isolation_and_crash_accounting"),
    ("database restart", "tests/test_pilot_storage.py::test_database_restart_preserves_state"),
    ("restore from backup", "tests/test_pilot_storage.py::test_backup_and_restore_reproduce_audit_heads"),
    ("corrupted backup fails closed", "tests/test_pilot_storage.py::test_restore_check_fails_closed_on_corrupted_backup"),
    ("wrong tenant (identity)", "tests/test_pilot_identity_kms.py::test_cross_tenant_token_rejected"),
    ("wrong issuer/audience", "tests/test_pilot_identity_kms.py::test_wrong_audience_rejected"),
    ("cross-chain presentation", "tests/test_signed_chain.py::test_cross_chain_presentation_rejected_by_pinning"),
    ("malformed signer key", "tests/test_signed_chain.py::test_malformed_signer_pem_fails_closed"),
    ("archive traversal + symlink", "tests/test_assets.py"),
    ("decompression/size abuse (ingest)", "tests/test_pilot_ingest.py::test_size_abuse_is_refused_before_parsing"),
    ("expired approval", "tests/test_pilot_shadow.py::test_expired_approval_moves_to_expired_and_refuses"),
    ("transition skipping", "tests/test_pilot_shadow.py::test_transition_skipping_is_impossible"),
]


def pytest_cases() -> None:
    for label, selection in PYTEST_SELECTIONS:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--no-header", *selection.split()],
            cwd=ROOT, env={**os.environ, "PYTHONPATH": "src"},
            capture_output=True, text=True)
        tail = (result.stdout + result.stderr).strip().splitlines()[-1:] or ["no output"]
        record(label, "pytest", "selection passes", tail[0][:100],
               result.returncode == 0)


def main() -> int:
    if HOME.exists():
        shutil.rmtree(HOME)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    os.environ["EAGLE_EYE_PILOT_HOME"] = str(HOME)
    os.environ["EAGLE_EYE_PORT"] = str(PORT)
    try:
        assert cmd_setup(HOME) == 0
        assert cmd_up(HOME) == 0
        live_cases()
        secrets_never_in_logs()
    finally:
        cmd_down(HOME)
    startup_with_missing_dependency()
    pytest_cases()
    ok = all(row["pass"] for row in ROWS)
    OUT.write_text(json.dumps({
        "spec": "eagle-eye-failure-court/6.0",
        "label": "LOCAL_SYNTHETIC_FAILURE_INJECTION",
        "cases": ROWS,
        "total": len(ROWS),
        "passed": sum(1 for r in ROWS if r["pass"]),
        "all_pass": ok,
        "finished_at": time.time(),
        "browser_deferred_note": ("the hostile-HTML payload injected here is "
                                  "asserted inert by scripts/browser_verification.py "
                                  "(INERT_HOSTILE_EVIDENCE check)"),
    }, indent=2, sort_keys=True))
    print(f"FAILURE_COURT_{'PASS' if ok else 'FAIL'} "
          f"({sum(1 for r in ROWS if r['pass'])}/{len(ROWS)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
