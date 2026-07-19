"""V6 object store + observability — fail-closed evidence bytes, clean logs."""

import hashlib
import json
import logging

import pytest

from eagle_eye.pilot.objectstore import (
    BackendUnavailable, FsObjectStore, ObjectCorrupted, ObjectMissing, S3Config)
from eagle_eye.pilot.observability import (
    HealthMonitor, JsonLogFormatter, METRICS, MetricsRegistry, REDACTION,
    bind_context, current_context, get_logger, log_event)


def test_put_get_roundtrip_and_idempotent_put(tmp_path):
    store = FsObjectStore(tmp_path / "objects")
    digest = store.put(b"evidence-bytes")
    assert digest == hashlib.sha256(b"evidence-bytes").hexdigest()
    assert store.get(digest) == b"evidence-bytes"
    assert store.put(b"evidence-bytes") == digest  # idempotent
    assert store.exists(digest)
    assert store.stats()["objects"] == 1


def test_missing_object_fails_closed(tmp_path):
    store = FsObjectStore(tmp_path / "objects")
    with pytest.raises(ObjectMissing):
        store.get("0" * 64)


def test_corrupted_object_fails_closed_on_read(tmp_path):
    store = FsObjectStore(tmp_path / "objects")
    digest = store.put(b"important evidence")
    path = store._path_for(digest)
    path.write_bytes(b"tampered evidence!!")
    with pytest.raises(ObjectCorrupted):
        store.get(digest)


def test_bad_digest_shapes_rejected(tmp_path):
    store = FsObjectStore(tmp_path / "objects")
    for bad in ("short", "Z" * 64, "../../../etc/passwd"):
        with pytest.raises(Exception):
            store.get(bad)


def test_s3_shape_fails_closed(monkeypatch):
    for var in ("EAGLE_EYE_PILOT_S3_ENDPOINT", "EAGLE_EYE_PILOT_S3_ACCESS_KEY",
                "EAGLE_EYE_PILOT_S3_SECRET_KEY"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(BackendUnavailable, match="NOT ESTABLISHED"):
        S3Config().connect()


# ---------------------------------------------------------------------------
# observability
# ---------------------------------------------------------------------------

def _format_line(logger_name="pilot.test", message="hello", **fields):
    record = logging.LogRecord(logger_name, logging.INFO, __file__, 1,
                               message, None, None)
    record.fields = fields
    return JsonLogFormatter().format(record)


def test_logs_are_structured_json_with_correlation_ids():
    bind_context(run_id="run-1", tenant_id="tenant-fixture-a",
                 request_id="req-9", trace_id="trace-7")
    line = _format_line(message="ingest accepted", event="ingest")
    parsed = json.loads(line)
    assert parsed["run_id"] == "run-1"
    assert parsed["tenant_id"] == "tenant-fixture-a"
    assert parsed["request_id"] == "req-9"
    assert parsed["trace_id"] == "trace-7"
    assert parsed["event"] == "ingest"
    assert set(current_context()) == {"run_id", "tenant_id", "request_id", "trace_id"}


def test_registered_secret_values_never_reach_log_lines():
    secret = "super-secret-evaluator-value-123"
    REDACTION.register(secret)
    line = _format_line(message=f"debug dump {secret}", detail=f"x={secret}")
    assert secret not in line
    assert "[REDACTED]" in line


def test_secret_looking_keys_are_redacted_by_name():
    line = _format_line(message="kv", api_key="AKIA123456789",
                        evaluator_secret="deadbeef" * 4, ok_field="visible")
    parsed = json.loads(line)
    assert parsed["api_key"] == "[REDACTED]"
    assert parsed["evaluator_secret"] == "[REDACTED]"
    assert parsed["ok_field"] == "visible"


def test_nested_payloads_are_scrubbed():
    line = _format_line(message="nested",
                        payload={"outer": {"password": "hunter2", "keep": "yes"},
                                 "list": [{"token": "abc123xyz"}]})
    parsed = json.loads(line)
    assert parsed["payload"]["outer"]["password"] == "[REDACTED]"
    assert parsed["payload"]["outer"]["keep"] == "yes"
    assert parsed["payload"]["list"][0]["token"] == "[REDACTED]"


def test_metrics_counters_and_timers():
    registry = MetricsRegistry()
    registry.inc("ingest.accepted")
    registry.inc("ingest.accepted", 2)
    with registry.timer("decision.latency"):
        pass
    snap = registry.snapshot()
    assert snap["counters"]["ingest.accepted"] == 3
    assert snap["durations"]["decision.latency"]["count"] == 1
    assert snap["label"] == "LOCAL_SYNTHETIC_PILOT_TELEMETRY"


def test_health_monitor_reports_degraded_not_hidden():
    monitor = HealthMonitor()
    monitor.register("storage", lambda: (True, "sqlite ok"))
    monitor.register("evaluator", lambda: (False, "socket missing"), required=True)
    monitor.register("optional-cache", lambda: (False, "absent"), required=False)
    report = monitor.report()
    assert report["ready"] is False
    assert report["status"] == "degraded"
    assert report["dependencies"]["storage"]["ok"] is True
    assert report["dependencies"]["evaluator"]["ok"] is False


def test_crashing_probe_is_a_failing_probe():
    monitor = HealthMonitor()

    def boom():
        raise RuntimeError("probe exploded")

    monitor.register("flaky", boom)
    report = monitor.report()
    assert report["ready"] is False
    assert "raised" in report["dependencies"]["flaky"]["detail"]


def test_get_logger_and_log_event_do_not_leak_registered_secrets(capsys):
    logger = get_logger("pilot.leaktest")
    REDACTION.register("registered-secret-token-xyz")
    log_event(logger, "action", note="carrying registered-secret-token-xyz along")
    captured = capsys.readouterr()
    stream = captured.out + captured.err
    assert "registered-secret-token-xyz" not in stream
    assert "[REDACTED]" in stream
