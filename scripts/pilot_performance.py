"""Pilot performance & reliability — LABELED local synthetic measurements.

Measures latencies/throughput for the pilot spine on THIS host against a
clearly-labeled synthetic workload. No enterprise-scale claims: these are
local reference numbers for regression tracking, not operational SLAs.

Regression thresholds are applied ONLY where the measurement is stable and
meaningful, and they are generous (order-of-magnitude guards against a
serious regression, not tight performance targets). Writes
artifacts/performance/PILOT_PERFORMANCE_RESULTS.json.

usage: PYTHONPATH=src python scripts/pilot_performance.py
"""

from __future__ import annotations

import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eagle_eye.pilot.identity_service import IdentityVerifier, LocalDevIssuer  # noqa: E402
from eagle_eye.pilot.ingest import IngestBoundary, SyntheticConnector  # noqa: E402
from eagle_eye.pilot.kms import EphemeralKeyProvider  # noqa: E402
from eagle_eye.pilot.objectstore import FsObjectStore  # noqa: E402
from eagle_eye.pilot.shadow import ShadowLifecycle  # noqa: E402
from eagle_eye.pilot.storage import PilotStorage  # noqa: E402

TENANT = "tenant-fixture-a"
HOME = ROOT / "artifacts" / "performance" / "perf-home"
OUT = ROOT / "artifacts" / "performance" / "PILOT_PERFORMANCE_RESULTS.json"

# generous order-of-magnitude regression guards (ms), local synthetic only
THRESHOLDS_MS = {
    "ingest_per_event_p50": 250.0,
    "decision_p50": 500.0,
    "approval_txn_p50": 400.0,
    "replay_p50": 800.0,
    "evidence_export_p50": 1500.0,
    "backup_p50": 2000.0,
}


def stat_block(samples_s: list[float]) -> dict[str, float]:
    ms = sorted(s * 1000.0 for s in samples_s)
    return {"count": len(ms),
            "p50_ms": round(statistics.median(ms), 2),
            "p95_ms": round(ms[max(0, int(len(ms) * 0.95) - 1)], 2),
            "max_ms": round(ms[-1], 2),
            "mean_ms": round(statistics.fmean(ms), 2)}


def main() -> int:
    import shutil
    if HOME.exists():
        shutil.rmtree(HOME)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    tracemalloc.start()
    store = PilotStorage(HOME / "pilot.sqlite3")
    store.migrate()
    store.ensure_tenant(TENANT, display_name="Perf", data_class="FIXTURE")
    signer = EphemeralKeyProvider()
    connector = SyntheticConnector(source_id="syn-perf", tenant_id=TENANT, seed=99)
    ingest = IngestBoundary(store, signer=signer,
                            sources={"syn-perf": connector.source_registration()})
    shadow = ShadowLifecycle(store, signer=signer)
    objects = FsObjectStore(HOME / "objects")
    issuer = LocalDevIssuer(tenants=[TENANT])
    verifier = IdentityVerifier(registry_entries=issuer.registry_entries())

    def principal(subject, roles):
        return verifier.verify(issuer.mint(subject=subject, tenant_id=TENANT,
                                           roles=roles), expected_tenant=TENANT)

    analyst = principal("perf-analyst", ["analyst"])
    approver = principal("perf-approver", ["approver"])
    operator = principal("perf-operator", ["operator"])

    results: dict[str, dict] = {}

    # ingest throughput (200 events)
    envelopes = connector.events(200)
    t0 = time.perf_counter()
    per_event = []
    digests = []
    for env in envelopes:
        s = time.perf_counter()
        r = ingest.ingest_envelope(TENANT, env)
        per_event.append(time.perf_counter() - s)
        if r.get("accepted"):
            digests.append(r["digest"])
    total = time.perf_counter() - t0
    results["ingest"] = {**stat_block(per_event),
                         "events": len(envelopes),
                         "throughput_events_per_s": round(len(envelopes) / total, 1)}

    # decision latency
    decision_samples = []
    from eagle_eye.pilot.service import PilotRuntime  # reuse decision logic
    runtime = PilotRuntime(HOME)  # separate runtime over the same home
    for _ in range(20):
        s = time.perf_counter()
        runtime.decision_preview(TENANT, digests[:8])
        decision_samples.append(time.perf_counter() - s)
    results["decision"] = stat_block(decision_samples)
    runtime.close()

    # approval-transaction + replay + export latency across 15 full loops
    approval_samples, replay_samples, export_samples = [], [], []
    for i in range(15):
        req = shadow.request(principal=analyst, action_id="reroute-lane",
                             evidence_ids=digests[i:i + 3], summary=f"perf {i}")
        rid = req["request_id"]
        s = time.perf_counter()
        shadow.approve(principal=approver, request_id=rid)
        approval_samples.append(time.perf_counter() - s)
        shadow.dispatch(principal=analyst, request_id=rid, idempotency_key=f"perf-{rid}")
        shadow.record_outcome(principal=analyst, request_id=rid,
                              observed={"predicted_delay_days": 10, "actual_delay_days": 9})
        s = time.perf_counter()
        shadow.replay(principal=analyst, request_id=rid)
        replay_samples.append(time.perf_counter() - s)
        s = time.perf_counter()
        shadow.export_evidence_room(principal=operator, request_id=rid, object_store=objects)
        export_samples.append(time.perf_counter() - s)
    results["approval_txn"] = stat_block(approval_samples)
    results["replay"] = stat_block(replay_samples)
    results["evidence_export"] = stat_block(export_samples)

    # backup timing
    backup_samples = []
    for _ in range(5):
        s = time.perf_counter()
        store.backup(HOME / "backups" / f"b{_}")
        backup_samples.append(time.perf_counter() - s)
    results["backup"] = stat_block(backup_samples)

    # restore timing (single)
    s = time.perf_counter()
    restore = PilotStorage.restore_check(HOME / "backups" / "b0")
    results["restore_check"] = {"ms": round((time.perf_counter() - s) * 1000, 2),
                                "heads_reproduced": restore["all_heads_reproduced"]}

    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    results["memory"] = {"peak_mb": round(peak / 1e6, 1),
                         "note": "in-process pilot workload only; the canonical "
                                 "gate runs each mechanism as a subprocess"}
    store.close()

    # regression checks (generous)
    regressions = []
    checks = {
        "ingest_per_event_p50": results["ingest"]["p50_ms"],
        "decision_p50": results["decision"]["p50_ms"],
        "approval_txn_p50": results["approval_txn"]["p50_ms"],
        "replay_p50": results["replay"]["p50_ms"],
        "evidence_export_p50": results["evidence_export"]["p50_ms"],
        "backup_p50": results["backup"]["p50_ms"],
    }
    for key, value in checks.items():
        if value > THRESHOLDS_MS[key]:
            regressions.append(f"{key}={value}ms > {THRESHOLDS_MS[key]}ms")

    ok = not regressions and restore["all_heads_reproduced"]
    OUT.write_text(json.dumps({
        "spec": "eagle-eye-pilot-performance/6.0",
        "label": "LOCAL_SYNTHETIC_WORKLOAD — not an operational-scale claim",
        "host_note": "single sandbox host; numbers are for regression tracking only",
        "results": results,
        "regression_thresholds_ms": THRESHOLDS_MS,
        "regressions": regressions,
        "pass": ok,
    }, indent=2, sort_keys=True))
    for name, block in results.items():
        if isinstance(block, dict) and "p50_ms" in block:
            print(f"{name}: p50={block['p50_ms']}ms p95={block.get('p95_ms')}ms")
    print(f"PILOT_PERFORMANCE_{'PASS' if ok else 'FAIL'}"
          + (f" regressions={regressions}" if regressions else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
