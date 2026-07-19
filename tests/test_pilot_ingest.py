"""V6 ingestion contract — acceptance path AND the quarantine/rejection court."""

import base64
import json
import time

import pytest

from eagle_eye.pilot.ingest import (
    ConnectorDisabled, FileReplayConnector, HttpWebhookConnector, IngestBoundary,
    INGEST_CONTRACT, MAX_EVENT_BYTES, SyntheticConnector, validate_event)
from eagle_eye.pilot.kms import EphemeralKeyProvider
from eagle_eye.pilot.storage import PilotStorage

TENANT = "tenant-fixture-a"


@pytest.fixture()
def boundary(tmp_path):
    store = PilotStorage(tmp_path / "pilot.sqlite3")
    store.migrate()
    store.ensure_tenant(TENANT, display_name="Fixture A", data_class="FIXTURE")
    store.ensure_tenant("tenant-fixture-b", display_name="Fixture B",
                        data_class="FIXTURE")
    connector = SyntheticConnector(source_id="syn-1", tenant_id=TENANT, seed=42)
    ingest = IngestBoundary(store, signer=EphemeralKeyProvider(),
                            sources={"syn-1": connector.source_registration()})
    yield ingest, connector, store
    store.close()


def test_signed_synthetic_events_are_accepted_with_receipts(boundary):
    ingest, connector, _ = boundary
    results = [ingest.ingest_envelope(TENANT, env) for env in connector.events(5)]
    assert all(r["accepted"] for r in results)
    receipt = results[0]["receipt"]
    assert receipt["data_class"] == "FIXTURE"
    assert receipt["receipt_signature_b64"]
    assert receipt["raw_event_sha256"] != receipt["digest"]  # raw ≠ normalized
    events = ingest.normalized_events(TENANT)
    assert len(events) == 5


def test_synthetic_connector_is_deterministic():
    a = SyntheticConnector(source_id="s", tenant_id=TENANT, seed=7)
    b = SyntheticConnector(source_id="s", tenant_id=TENANT, seed=7)
    assert [e["event"] for e in a.events(3, start_at=1000.0)] == \
           [e["event"] for e in b.events(3, start_at=1000.0)]


def test_unsigned_ingestion_is_quarantined(boundary):
    ingest, connector, _ = boundary
    envelope = connector.events(1)[0]
    del envelope["signature_b64"]
    result = ingest.ingest_envelope(TENANT, envelope)
    assert result["state"] == "QUARANTINED"
    assert any("unsigned" in r for r in result["reasons"])


def test_bad_signature_and_wrong_key_are_quarantined(boundary):
    ingest, connector, _ = boundary
    envelope = connector.events(1)[0]
    envelope["signature_b64"] = base64.b64encode(b"\x00" * 64).decode()
    result = ingest.ingest_envelope(TENANT, envelope)
    assert result["state"] == "QUARANTINED"
    other = SyntheticConnector(source_id="syn-1", tenant_id=TENANT, seed=9)
    forged = other.events(1)[0]  # right source_id, unregistered key
    result2 = ingest.ingest_envelope(TENANT, forged)
    assert result2["state"] == "QUARANTINED"
    assert any("key does not match" in r for r in result2["reasons"])


def test_unknown_source_and_wrong_tenant_are_quarantined(boundary):
    ingest, connector, _ = boundary
    stranger = SyntheticConnector(source_id="mystery", tenant_id=TENANT, seed=1)
    result = ingest.ingest_envelope(TENANT, stranger.events(1)[0])
    assert result["state"] == "QUARANTINED"
    assert any("unknown source" in r for r in result["reasons"])
    # registered source, but the event names a different tenant
    envelope = connector.events(1)[0]
    envelope["event"]["tenant_id"] = "tenant-fixture-b"
    result2 = ingest.ingest_envelope("tenant-fixture-b", envelope)
    assert result2["state"] == "QUARANTINED"  # source bound to tenant-a


def test_schema_defects_are_quarantined_with_reasons(boundary):
    ingest, connector, _ = boundary
    envelope = connector.events(1)[0]
    envelope["event"]["payload"]["severity"] = 7.5  # out of [0,1]
    envelope["signature_b64"] = base64.b64encode(b"x").decode()
    # re-sign properly so we reach schema validation, not signature failure
    good = connector.events(1)[0]
    good["event"]["payload"] = {"lane": "l", "disruption_class": "d",
                                "severity": 7.5, "description": "bad"}
    resigned = connector._sign_envelope(good["event"])
    result = ingest.ingest_envelope(TENANT, resigned)
    assert result["state"] == "QUARANTINED"
    assert any("severity" in r for r in result["reasons"])
    entries = ingest.quarantine_entries(TENANT)
    assert entries and entries[-1]["reasons"]


def test_validate_event_pure_function_reports_all_defects():
    problems = validate_event({"contract_version": "nope", "event_kind": "weird",
                               "payload": []})
    assert len(problems) >= 5


def test_size_abuse_is_refused_before_parsing(boundary):
    ingest, _, _ = boundary
    oversized = b"{" + b"a" * MAX_EVENT_BYTES
    result = ingest.ingest_raw(TENANT, oversized)
    assert result["state"] == "QUARANTINED"
    assert any("size" in r or "bytes" in r for r in result["reasons"])
    malformed = ingest.ingest_raw(TENANT, b"{not json")
    assert malformed["state"] == "QUARANTINED"


def test_replay_and_duplicate_idempotency_rejected(boundary):
    ingest, connector, _ = boundary
    envelope = connector.events(1)[0]
    assert ingest.ingest_envelope(TENANT, envelope)["accepted"]
    replay = ingest.ingest_envelope(TENANT, envelope)  # identical content
    assert replay["state"] == "REPLAY_REJECTED"
    # different content, reused idempotency key
    other = connector.events(2)[1]
    other["event"]["idempotency_key"] = envelope["event"]["idempotency_key"]
    resigned = connector._sign_envelope(other["event"])
    duplicate = ingest.ingest_envelope(TENANT, resigned)
    assert duplicate["state"] == "DUPLICATE_IDEMPOTENCY_KEY"


def test_late_events_are_labeled_not_hidden(boundary):
    ingest, connector, _ = boundary
    envelope = connector.events(1, start_at=time.time() - 30 * 24 * 3600)[0]
    result = ingest.ingest_envelope(TENANT, envelope)
    assert result["accepted"] and result["receipt"]["late"] is True


def test_corrections_supersede_without_mutating_history(boundary):
    ingest, connector, _ = boundary
    original = connector.events(1)[0]
    accepted = ingest.ingest_envelope(TENANT, original)
    correction_event = {
        "contract_version": INGEST_CONTRACT,
        "event_kind": "correction",
        "source_id": "syn-1", "tenant_id": TENANT,
        "occurred_at": time.time(),
        "idempotency_key": "corr-1",
        "supersedes_digest": accepted["digest"],
        "payload": {"reason": "severity restated after carrier confirmation"},
    }
    corrected = ingest.ingest_envelope(TENANT, connector._sign_envelope(correction_event))
    assert corrected["accepted"]
    trace = ingest.provenance(TENANT, accepted["digest"])
    assert corrected["digest"] in trace["superseded_by"]
    assert trace["digest_recomputed_ok"]
    events = ingest.normalized_events(TENANT)
    flagged = [e for e in events if e["digest"] == accepted["digest"]][0]
    assert flagged["superseded_by_correction"] is True
    # a correction referencing an unknown digest is quarantined
    dangling = dict(correction_event, idempotency_key="corr-2",
                    supersedes_digest="0" * 64)
    result = ingest.ingest_envelope(TENANT, connector._sign_envelope(dangling))
    assert result["state"] == "QUARANTINED"


def test_provenance_is_traceable_and_fails_closed(boundary):
    ingest, connector, _ = boundary
    accepted = ingest.ingest_envelope(TENANT, connector.events(1)[0])
    trace = ingest.provenance(TENANT, accepted["digest"])
    assert trace["receipt"]["normalization"] == "eagle-eye-ingest-normalize/1.0"
    assert trace["source_registered"]
    with pytest.raises(KeyError):
        ingest.provenance(TENANT, "f" * 64)


def test_file_replay_connector_jsonl_and_csv(boundary, tmp_path):
    ingest, connector, store = boundary
    fixture = connector.export_jsonl(tmp_path / "events.jsonl", 3)
    replayer = FileReplayConnector(source_id="file-1", tenant_id=TENANT)
    ingest.sources["file-1"] = replayer.source_registration()
    # jsonl envelopes were signed by syn-1, replay them verbatim
    results = [ingest.ingest_envelope(TENANT, env)
               for env in replayer.iter_jsonl(fixture)]
    assert all(r["accepted"] for r in results)
    csv_path = tmp_path / "events.csv"
    csv_path.write_text(
        "lane,disruption_class,severity,occurred_at,description,idempotency_key\n"
        f"lane-asia-uswest,port_congestion,0.4,{time.time()},csv row,csv-key-1\n")
    csv_results = [ingest.ingest_envelope(TENANT, env)
                   for env in replayer.iter_csv(csv_path)]
    assert all(r["accepted"] for r in csv_results)
    assert csv_results[0]["receipt"]["source_id"] == "file-1"


def test_http_webhook_connector_is_disabled_fail_closed():
    connector = HttpWebhookConnector()
    assert connector.enabled is False
    with pytest.raises(ConnectorDisabled):
        connector.start()
    with pytest.raises(ConnectorDisabled):
        connector.receive({})


def test_every_acceptance_lands_in_the_audit_chain(boundary):
    ingest, connector, store = boundary
    for env in connector.events(3):
        ingest.ingest_envelope(TENANT, env)
    events = store.audit_events(TENANT)
    assert sum(1 for e in events if e["event_type"] == "INGEST_ACCEPTED") == 3
