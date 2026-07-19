"""Observability — structured logs, correlation, redaction, metrics, health.

- Structured JSON logs on every pilot component, each line carrying the
  correlation ids bound via contextvars (run_id / tenant_id / request_id /
  trace_id) so one request can be followed across process boundaries (the
  evaluator service receives and echoes the trace id).
- SECRETS NEVER REACH THE LOG STREAM: a RedactionFilter scrubs (a) values
  registered at runtime (evaluator secrets, passphrases, tokens) and
  (b) values of keys whose names look secret-bearing. There is an
  executable redaction test in the failure court.
- A small in-process metrics registry (counters + duration histograms)
  exported as JSON for the cockpit /api/pilot/metrics endpoint.
- Health/readiness aggregation over named dependency probes.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import threading
import time
from typing import Any, Callable

OBSERVABILITY_SPEC = "eagle-eye-pilot-observability/6.0"

# -- correlation --------------------------------------------------------------

run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="")
tenant_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("tenant_id", default="")
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def bind_context(**kwargs: str) -> None:
    mapping = {"run_id": run_id_var, "tenant_id": tenant_id_var,
               "request_id": request_id_var, "trace_id": trace_id_var}
    for key, value in kwargs.items():
        if key in mapping and value is not None:
            mapping[key].set(value)


def current_context() -> dict[str, str]:
    return {name: var.get() for name, var in
            (("run_id", run_id_var), ("tenant_id", tenant_id_var),
             ("request_id", request_id_var), ("trace_id", trace_id_var))
            if var.get()}


# -- redaction ------------------------------------------------------------------

_SECRET_KEY_PATTERN = re.compile(
    r"(secret|token|password|passphrase|private_key|credential|api_key)",
    re.IGNORECASE)


class RedactionRegistry:
    """Process-wide registry of literal secret values that must never appear
    in any log line. Components register secrets as they mint them."""

    def __init__(self):
        self._values: set[str] = set()
        self._lock = threading.Lock()

    def register(self, value: str) -> None:
        if value and len(value) >= 6:
            with self._lock:
                self._values.add(value)

    def scrub_text(self, text: str) -> str:
        with self._lock:
            for value in self._values:
                if value in text:
                    text = text.replace(value, "[REDACTED]")
        return text

    def scrub_value(self, key: str, value: Any) -> Any:
        if isinstance(value, str):
            if _SECRET_KEY_PATTERN.search(key or ""):
                return "[REDACTED]"
            return self.scrub_text(value)
        if isinstance(value, dict):
            return {k: self.scrub_value(k, v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.scrub_value(key, v) for v in value]
        return value


REDACTION = RedactionRegistry()


class JsonLogFormatter(logging.Formatter):
    """One JSON object per line; correlation ids attached; secrets scrubbed."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "ts": round(record.created, 3),
            "level": record.levelname,
            "logger": record.name,
            "message": REDACTION.scrub_text(record.getMessage()),
            **current_context(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            entry.update({k: REDACTION.scrub_value(k, v) for k, v in extra.items()})
        if record.exc_info and record.exc_info[0]:
            entry["error_class"] = record.exc_info[0].__name__
        return json.dumps(entry, sort_keys=True, default=str)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not any(isinstance(h.formatter, JsonLogFormatter)
               for h in logger.handlers if h.formatter):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


def log_event(logger: logging.Logger, message: str, **fields: Any) -> None:
    logger.info(message, extra={"fields": fields})


# -- metrics ---------------------------------------------------------------------

class MetricsRegistry:
    """Counters and duration observations, exported as JSON. Local pilot
    telemetry — clearly labeled, no enterprise-scale claims."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._durations: dict[str, list[float]] = {}

    def inc(self, name: str, by: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + by

    def observe(self, name: str, seconds: float) -> None:
        with self._lock:
            self._durations.setdefault(name, []).append(seconds)

    def timer(self, name: str) -> "_Timer":
        return _Timer(self, name)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            durations = {}
            for name, values in self._durations.items():
                ordered = sorted(values)
                durations[name] = {
                    "count": len(ordered),
                    "total_s": round(sum(ordered), 4),
                    "p50_ms": round(ordered[len(ordered) // 2] * 1000, 2),
                    "max_ms": round(ordered[-1] * 1000, 2),
                }
            return {"spec": OBSERVABILITY_SPEC,
                    "label": "LOCAL_SYNTHETIC_PILOT_TELEMETRY",
                    "counters": dict(self._counters),
                    "durations": durations}


class _Timer:
    def __init__(self, registry: MetricsRegistry, name: str):
        self.registry, self.name = registry, name

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.registry.observe(self.name, time.perf_counter() - self._start)


METRICS = MetricsRegistry()


# -- health ----------------------------------------------------------------------

class HealthMonitor:
    """Aggregates named dependency probes into health/readiness reports.
    A probe returns (ok: bool, detail: str). Readiness = every REQUIRED
    probe ok; health lists each dependency honestly (degraded, not hidden)."""

    def __init__(self):
        self._probes: dict[str, tuple[Callable[[], tuple[bool, str]], bool]] = {}

    def register(self, name: str, probe: Callable[[], tuple[bool, str]],
                 *, required: bool = True) -> None:
        self._probes[name] = (probe, required)

    def report(self) -> dict[str, Any]:
        deps = {}
        ready = True
        for name, (probe, required) in self._probes.items():
            try:
                ok, detail = probe()
            except Exception as exc:  # a crashing probe is a failing probe
                ok, detail = False, f"probe raised {type(exc).__name__}"
            deps[name] = {"ok": ok, "required": required, "detail": detail}
            if required and not ok:
                ready = False
        return {"spec": OBSERVABILITY_SPEC, "ready": ready,
                "status": "ready" if ready else "degraded",
                "dependencies": deps, "checked_at": time.time()}
