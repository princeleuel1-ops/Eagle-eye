"""V6 evaluator process isolation — the boundary is an OS process, not a class.

Two layers of tests:
  - protocol/logic tests drive EvaluatorService.handle_frame in-process
    (fast, deterministic), against a real durable EvaluatorState;
  - PROCESS tests launch the actual service as a subprocess over a unix
    socket and prove the crash/restart/no-refund semantics for real.

Claim discipline: these tests establish MECHANICALLY VERIFIED process
isolation on one host. They do NOT establish organizational isolation.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from eagle_eye.sealed_evaluator import commitment_for
from eagle_eye.pilot.evaluator_service import (
    EVALUATOR_PROTO, EvaluatorClient, EvaluatorRefused, EvaluatorService,
    EvaluatorState, EvaluatorUnavailable, MAX_FRAME_BYTES)

TENANT = "tenant-fixture-a"
RUN = "run-iso-1"
TOKEN = "test-client-token-0123456789abcdef"

CHAMPION = {"selector.k_max": 10, "selector.min_score_milli": 4000}
CHALLENGER = {"selector.k_max": 8, "selector.min_score_milli": 4000}


# ---------------------------------------------------------------------------
# in-process protocol/logic layer
# ---------------------------------------------------------------------------

@pytest.fixture()
def service(tmp_path):
    state = EvaluatorState(state_dir=tmp_path / "state", tenant_id=TENANT,
                           run_id=RUN, max_looks=3)
    svc = EvaluatorService(socket_path=tmp_path / "sock", client_token=TOKEN,
                           state=state)
    yield svc
    state.close()


def call(svc: EvaluatorService, op: str, **fields):
    frame = json.dumps({"spec": EVALUATOR_PROTO, "op": op, "auth": TOKEN,
                        **fields}).encode()
    return svc.handle_frame(frame)


def predictions_from_contexts(contexts, *, loc_offset=0.0):
    """A cheap, honest local 'candidate': mean of observed prior outcomes."""
    cases = []
    for ctx in contexts:
        blocks = ctx["compiled"]["prior_blocks"]
        observed = [b["realized"]["log_final_delay"] for b in blocks
                    if b.get("boundary") == "prior"] or [1.0]
        loc = sum(observed) / len(observed) + loc_offset
        cases.append({"case_id": ctx["case_id"], "abstained": False,
                      "dist": {"loc": loc, "scale": 0.9, "df": None}})
    return cases


def test_evaluator_socket_path_stays_under_af_unix_limit():
    """Portability: even a pathologically deep pilot home must yield a socket
    path well under the AF_UNIX limit (~104 macOS / ~108 Linux). Regression
    for the clean-extraction bind failure."""
    from eagle_eye.pilot.ops import evaluator_socket_path
    deep = "/Users/Apple/Projects/eagle-eye-zenith/" + "/".join(["nested"] * 20) \
        + "/EAGLE_EYE_ZENITH_FABLE_HANDOFF_V8/artifacts/pilot/home"
    path = str(evaluator_socket_path(deep))
    assert len(path) < 100, f"socket path too long ({len(path)}): {path}"
    # deterministic: same home → same socket
    assert evaluator_socket_path(deep) == evaluator_socket_path(deep)


def test_status_exposes_commitment_but_never_the_secret(service):
    status = call(service, "status")
    assert status["ok"] and status["lifecycle"] == "INITIALIZED"
    assert len(status["commitment"]) == 64
    assert "promotion" in status["suite_commitments"]
    blob = json.dumps(status)
    assert service.state._secret not in blob


def test_unauthenticated_and_malformed_frames_are_refused(service):
    bad_auth = service.handle_frame(json.dumps(
        {"spec": EVALUATOR_PROTO, "op": "status", "auth": "wrong"}).encode())
    assert bad_auth["code"] == "UNAUTHENTICATED"
    assert service.handle_frame(b"{not json")["code"] == "MALFORMED"
    assert service.handle_frame(json.dumps(
        {"spec": "bogus/1", "op": "status", "auth": TOKEN}).encode())["code"] == "BAD_SPEC"
    assert call(service, "self_destruct")["code"] == "UNKNOWN_OP"
    huge = json.dumps({"spec": EVALUATOR_PROTO, "op": "status", "auth": TOKEN,
                       "pad": "a" * MAX_FRAME_BYTES}).encode()
    assert service.handle_frame(huge)["code"] == "FRAME_TOO_LARGE"
    # the service is still alive and sane afterwards
    assert call(service, "status")["ok"]


def test_reserve_charges_before_contexts_and_ships_no_truth(service):
    assert call(service, "status")["looks_spent"] == 0
    reserved = call(service, "reserve_look", kind="promotion",
                    candidate_id="cand-1", snapshot_id="snap-1", nonce="n-1",
                    champion_config=CHAMPION, challenger_config=CHALLENGER)
    assert reserved["ok"] and reserved["look_index"] == 1
    # the look is charged even though nothing was submitted
    assert call(service, "status")["looks_spent"] == 1
    # contexts contain prior-task training data but NO holdout truth
    wire = json.dumps(reserved)
    assert '"truth"' not in wire
    assert '"outcomes"' not in wire
    assert '"hyper"' not in wire
    assert len(reserved["champion_contexts"]) > 30


def test_full_look_roundtrip_produces_precommitted_statistics(service):
    reserved = call(service, "reserve_look", kind="promotion",
                    candidate_id="cand-2", snapshot_id="snap-1", nonce="n-2",
                    champion_config=CHAMPION, challenger_config=CHALLENGER)
    champ = predictions_from_contexts(reserved["champion_contexts"])
    chall = predictions_from_contexts(reserved["challenger_contexts"], loc_offset=0.02)
    result = call(service, "submit_result", look_id=reserved["look_id"],
                  champion_cases=champ, challenger_cases=chall)
    assert result["ok"] and result["terminal_status"] == "SUCCEEDED"
    stats = result["statistics"]
    assert stats["n"] == len(champ)
    assert "ci_upper" in stats and "significant_improvement" in stats


def test_replayed_nonce_refused_before_charge(service):
    call(service, "reserve_look", kind="promotion", candidate_id="c",
         snapshot_id="s", nonce="dup", champion_config=CHAMPION,
         challenger_config=CHALLENGER)
    spent = call(service, "status")["looks_spent"]
    refused = call(service, "reserve_look", kind="promotion", candidate_id="c",
                   snapshot_id="s", nonce="dup", champion_config=CHAMPION,
                   challenger_config=CHALLENGER)
    assert refused["code"] == "NONCE_REPLAY"
    assert call(service, "status")["looks_spent"] == spent  # no charge on refusal


def test_budget_exhaustion_refuses_pre_charge(service):
    for index in range(3):  # max_looks=3 in the fixture
        call(service, "reserve_look", kind="promotion", candidate_id="c",
             snapshot_id="s", nonce=f"b-{index}", champion_config=CHAMPION,
             challenger_config=CHALLENGER)
    refused = call(service, "reserve_look", kind="promotion", candidate_id="c",
                   snapshot_id="s", nonce="b-over", champion_config=CHAMPION,
                   challenger_config=CHALLENGER)
    assert refused["code"] == "BUDGET"
    assert call(service, "status")["looks_spent"] == 3


def test_submission_after_deadline_consumes_look_as_timed_out(service):
    reserved = call(service, "reserve_look", kind="promotion", candidate_id="c",
                    snapshot_id="s", nonce="t-1", deadline_s=0.2,
                    champion_config=CHAMPION, challenger_config=CHALLENGER)
    time.sleep(0.35)
    late = call(service, "submit_result", look_id=reserved["look_id"],
                champion_cases=[], challenger_cases=[])
    assert late["code"] == "TIMED_OUT" and late["look_consumed"] is True
    resettle = call(service, "submit_result", look_id=reserved["look_id"],
                    champion_cases=[], challenger_cases=[])
    assert resettle["code"] == "ALREADY_SETTLED"  # no refund, no re-settle


def test_malformed_submission_consumes_look_as_rejected(service):
    reserved = call(service, "reserve_look", kind="promotion", candidate_id="c",
                    snapshot_id="s", nonce="m-1", champion_config=CHAMPION,
                    challenger_config=CHALLENGER)
    bad = call(service, "submit_result", look_id=reserved["look_id"],
               champion_cases=[{"case_id": "nope", "abstained": False,
                                "dist": {"loc": 0.0, "scale": -1}}],
               challenger_cases=[])
    assert bad["code"] == "REJECTED" and bad["look_consumed"] is True
    assert call(service, "status")["looks_spent"] >= 1


def test_final_audit_is_one_shot(service):
    call(service, "reserve_look", kind="final_audit", candidate_id="champ",
         snapshot_id="s", nonce="f-1", champion_config=CHAMPION,
         challenger_config=CHAMPION)
    again = call(service, "reserve_look", kind="final_audit", candidate_id="champ",
                 snapshot_id="s", nonce="f-2", champion_config=CHAMPION,
                 challenger_config=CHAMPION)
    assert again["code"] == "FINAL_ONESHOT"


def test_lifecycle_finalize_then_reveal_and_no_backwards(service):
    early = call(service, "reveal")
    assert early["code"] == "REVEAL_REFUSED"  # reveal before FINALIZED hard-fails
    assert call(service, "finalize")["lifecycle"] == "FINALIZED"
    assert call(service, "finalize")["code"] == "LIFECYCLE"  # irreversible
    blocked = call(service, "reserve_look", kind="promotion", candidate_id="c",
                   snapshot_id="s", nonce="post-final", champion_config=CHAMPION,
                   challenger_config=CHALLENGER)
    assert blocked["code"] == "LIFECYCLE"
    revealed = call(service, "reveal")
    assert revealed["ok"]
    assert commitment_for(revealed["evaluator_secret"],
                          revealed["secret_provenance"]) == revealed["seed_commitment"]


# ---------------------------------------------------------------------------
# real-process layer
# ---------------------------------------------------------------------------

def _spawn(tmp_path: Path, run_id: str = "run-proc-1", max_looks: int = 5):
    token_file = tmp_path / "client.token"
    if not token_file.exists():
        token_file.write_text(TOKEN)
        os.chmod(token_file, 0o600)
    # short socket path (system temp dir) so a deep tmp_path cannot exceed the
    # AF_UNIX length limit — the same portability rule the pilot ops use.
    from eagle_eye.pilot.ops import evaluator_socket_path
    sock = evaluator_socket_path(tmp_path / run_id)
    state_dir = tmp_path / "state"
    env = {**os.environ, "PYTHONPATH": str(Path.cwd() / "src")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "eagle_eye.pilot.evaluator_service",
         "--socket", str(sock), "--state-dir", str(state_dir),
         "--token-file", str(token_file), "--tenant", TENANT,
         "--run-id", run_id, "--max-looks", str(max_looks)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    deadline = time.time() + 30
    while time.time() < deadline:
        if sock.exists():
            try:
                probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                probe.connect(str(sock))
                probe.close()
                break
            except OSError:
                pass
        if proc.poll() is not None:
            raise RuntimeError(f"service died on start:\n{proc.stdout.read()}")
        time.sleep(0.1)
    else:
        proc.kill()
        raise RuntimeError("service socket never appeared")
    return proc, EvaluatorClient(sock, TOKEN)


def test_process_boundary_secret_isolation_and_crash_accounting(tmp_path):
    proc, client = _spawn(tmp_path)
    try:
        status = client.request("status")
        commitment = status["commitment"]
        assert status["looks_spent"] == 0

        # candidate-side process (this test) never has the secret anywhere:
        # its own environment and the wire payloads contain only commitments.
        reserved = client.request(
            "reserve_look", kind="promotion", candidate_id="cand-x",
            snapshot_id="snap-x", nonce="proc-n1",
            champion_config=CHAMPION, challenger_config=CHALLENGER)
        assert client.request("status")["looks_spent"] == 1

        # KILL -9 the evaluator mid-look (client holds an open reservation)
        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=10)
        with pytest.raises(EvaluatorUnavailable):
            client.request("status")

        # restart on the SAME durable state: the dangling look is swept to a
        # terminal FAILED, stays consumed, and the commitment is unchanged
        proc2, client2 = _spawn(tmp_path)
        try:
            status2 = client2.request("status")
            assert status2["commitment"] == commitment  # same durable secret
            assert status2["looks_spent"] == 1          # no refund
            assert status2["swept_on_start"] == 1
            late = client2.request.__self__  # readable alias; submit the dead look
            with pytest.raises(EvaluatorRefused) as refusal:
                client2.request("submit_result", look_id=reserved["look_id"],
                                champion_cases=[], challenger_cases=[])
            assert refusal.value.code == "ALREADY_SETTLED"
            assert refusal.value.look_consumed is True
            # a nonce charged before the crash stays burned after restart
            with pytest.raises(EvaluatorRefused) as replay:
                client2.request("reserve_look", kind="promotion",
                                candidate_id="cand-x", snapshot_id="snap-x",
                                nonce="proc-n1", champion_config=CHAMPION,
                                challenger_config=CHALLENGER)
            assert replay.value.code == "NONCE_REPLAY"
        finally:
            proc2.send_signal(signal.SIGTERM)
            proc2.wait(timeout=10)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_process_lifecycle_survives_restart_and_logs_hold_no_secret(tmp_path):
    proc, client = _spawn(tmp_path, run_id="run-proc-2")
    try:
        client.request("finalize")
    finally:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
    output_first = proc.stdout.read() if proc.stdout else ""

    # restart: FINALIZED persisted; reveal works; further looks refused
    proc2, client2 = _spawn(tmp_path, run_id="run-proc-2")
    try:
        status = client2.request("status")
        assert status["lifecycle"] == "FINALIZED"
        with pytest.raises(EvaluatorRefused) as blocked:
            client2.request("reserve_look", kind="promotion", candidate_id="c",
                            snapshot_id="s", nonce="post-restart",
                            champion_config=CHAMPION, challenger_config=CHALLENGER)
        assert blocked.value.code == "LIFECYCLE"
        revealed = client2.request("reveal")
        secret = revealed["evaluator_secret"]
        assert commitment_for(secret, revealed["secret_provenance"]) == status["commitment"]
    finally:
        proc2.send_signal(signal.SIGTERM)
        proc2.wait(timeout=10)
    output_second = proc2.stdout.read() if proc2.stdout else ""

    # the secret text never appears in either process's log stream, and
    # neither does the client token (redaction + custody discipline)
    for stream in (output_first, output_second):
        assert secret not in stream
        assert TOKEN not in stream


def test_client_against_missing_socket_fails_closed(tmp_path):
    client = EvaluatorClient(tmp_path / "missing.sock", TOKEN)
    with pytest.raises(EvaluatorUnavailable):
        client.request("status")
