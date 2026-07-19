"""V6 shadow lifecycle — full loop, dual control, expiry, evidence freezing."""

import json
import time
import zipfile
import io

import pytest

from eagle_eye.pilot.identity_service import AuthorizationError, IdentityVerifier, LocalDevIssuer
from eagle_eye.pilot.ingest import IngestBoundary, SyntheticConnector
from eagle_eye.pilot.kms import EphemeralKeyProvider
from eagle_eye.pilot.objectstore import FsObjectStore
from eagle_eye.pilot.shadow import (
    ALLOWED_TRANSITIONS, EvidenceBindingError, ShadowError, ShadowLifecycle)
from eagle_eye.pilot.storage import PilotStorage

TENANT = "tenant-fixture-a"


@pytest.fixture()
def rig(tmp_path):
    store = PilotStorage(tmp_path / "pilot.sqlite3")
    store.migrate()
    store.ensure_tenant(TENANT, display_name="Fixture A", data_class="FIXTURE")
    signer = EphemeralKeyProvider()
    connector = SyntheticConnector(source_id="syn-1", tenant_id=TENANT, seed=11)
    ingest = IngestBoundary(store, signer=signer,
                            sources={"syn-1": connector.source_registration()})
    digests = [ingest.ingest_envelope(TENANT, env)["digest"]
               for env in connector.events(3)]
    issuer = LocalDevIssuer(tenants=[TENANT])
    verifier = IdentityVerifier(registry_entries=issuer.registry_entries())

    def principal(subject, roles):
        return verifier.verify(issuer.mint(subject=subject, tenant_id=TENANT,
                                           roles=roles), expected_tenant=TENANT)

    lifecycle = ShadowLifecycle(store, signer=signer)
    objects = FsObjectStore(tmp_path / "objects")
    yield {"store": store, "ingest": ingest, "connector": connector,
           "digests": digests, "principal": principal, "lifecycle": lifecycle,
           "objects": objects}
    store.close()


def run_to_state(rig, target_state, *, request_kw=None):
    lifecycle = rig["lifecycle"]
    analyst = rig["principal"]("user-analyst", ["analyst"])
    approver = rig["principal"]("user-approver", ["approver"])
    requested = lifecycle.request(principal=analyst, action_id="act-1",
                                  evidence_ids=rig["digests"][:2],
                                  summary="expedite alternate supplier",
                                  **(request_kw or {}))
    rid = requested["request_id"]
    if target_state == "AWAITING_INDEPENDENT_APPROVAL":
        return rid, analyst, approver
    lifecycle.approve(principal=approver, request_id=rid)
    if target_state == "APPROVED_SHADOW":
        return rid, analyst, approver
    lifecycle.dispatch(principal=analyst, request_id=rid, idempotency_key=f"d-{rid}")
    if target_state == "OUTCOME_PENDING":
        return rid, analyst, approver
    lifecycle.record_outcome(principal=analyst, request_id=rid,
                             observed={"predicted_delay_days": 12.0,
                                       "actual_delay_days": 10.5})
    if target_state == "OUTCOME_RECORDED":
        return rid, analyst, approver
    lifecycle.replay(principal=analyst, request_id=rid)
    return rid, analyst, approver


def test_full_loop_reaches_replay_verified_with_audited_transitions(rig):
    rid, analyst, _ = run_to_state(rig, "REPLAY_VERIFIED")
    lifecycle = rig["lifecycle"]
    assert lifecycle.state_of(TENANT, rid) == "REPLAY_VERIFIED"
    timeline = lifecycle.timeline(TENANT, rid)
    path = [(t["from_state"], t["to_state"]) for t in timeline]
    assert path == [("REQUESTED", "AWAITING_INDEPENDENT_APPROVAL"),
                    ("AWAITING_INDEPENDENT_APPROVAL", "APPROVED_SHADOW"),
                    ("APPROVED_SHADOW", "SHADOW_DISPATCHED"),
                    ("SHADOW_DISPATCHED", "OUTCOME_PENDING"),
                    ("OUTCOME_PENDING", "OUTCOME_RECORDED"),
                    ("OUTCOME_RECORDED", "REPLAY_VERIFIED")]
    # every transition is also an audit event
    events = rig["store"].audit_events(TENANT)
    transitions = [e for e in events if e["event_type"] == "SHADOW_TRANSITION"]
    assert len(transitions) == len(timeline)


def test_no_transition_without_authorization(rig):
    lifecycle = rig["lifecycle"]
    viewer = rig["principal"]("user-viewer", ["auditor"])
    with pytest.raises(AuthorizationError):
        lifecycle.request(principal=viewer, action_id="a",
                          evidence_ids=rig["digests"], summary="nope")
    rid, analyst, approver = run_to_state(rig, "AWAITING_INDEPENDENT_APPROVAL")
    with pytest.raises(AuthorizationError):
        lifecycle.approve(principal=analyst, request_id=rid)  # analyst ≠ approver role


def test_self_approval_rejected_even_with_both_roles(rig):
    lifecycle = rig["lifecycle"]
    dual = rig["principal"]("user-both", ["analyst", "approver"])
    requested = lifecycle.request(principal=dual, action_id="act-2",
                                  evidence_ids=rig["digests"][:1], summary="x")
    with pytest.raises(ShadowError, match="dual control|approval refused"):
        lifecycle.approve(principal=dual, request_id=requested["request_id"])


def test_duplicate_approval_rejected(rig):
    rid, _, approver = run_to_state(rig, "APPROVED_SHADOW")
    with pytest.raises(ShadowError, match="approval refused in state"):
        rig["lifecycle"].approve(principal=approver, request_id=rid)


def test_transition_skipping_is_impossible(rig):
    lifecycle = rig["lifecycle"]
    rid, analyst, _ = run_to_state(rig, "AWAITING_INDEPENDENT_APPROVAL")
    # dispatch straight from AWAITING (skipping approval) refuses
    with pytest.raises(ShadowError, match="dispatch refused in state"):
        lifecycle.dispatch(principal=analyst, request_id=rid, idempotency_key="skip")
    with pytest.raises(ShadowError, match="outcome refused in state"):
        lifecycle.record_outcome(principal=analyst, request_id=rid, observed={})
    with pytest.raises(ShadowError, match="replay requires"):
        lifecycle.replay(principal=analyst, request_id=rid)
    # and the transition map itself has no skipping edge
    assert "SHADOW_DISPATCHED" not in ALLOWED_TRANSITIONS["AWAITING_INDEPENDENT_APPROVAL"]


def test_expired_approval_moves_to_expired_and_refuses(rig):
    lifecycle = rig["lifecycle"]
    analyst = rig["principal"]("user-analyst", ["analyst"])
    approver = rig["principal"]("user-approver", ["approver"])
    requested = lifecycle.request(principal=analyst, action_id="act-exp",
                                  evidence_ids=rig["digests"][:1], summary="x")
    rid = requested["request_id"]
    lifecycle.approve(principal=approver, request_id=rid, expires_in_s=0.05)
    time.sleep(0.1)
    with pytest.raises(ShadowError, match="expired"):
        lifecycle.dispatch(principal=analyst, request_id=rid, idempotency_key="late")
    assert lifecycle.state_of(TENANT, rid) == "EXPIRED"


def test_idempotent_dispatch_same_key_same_receipt_different_key_refused(rig):
    lifecycle = rig["lifecycle"]
    rid, analyst, _ = run_to_state(rig, "APPROVED_SHADOW")
    first = lifecycle.dispatch(principal=analyst, request_id=rid,
                               idempotency_key="dispatch-1")
    replay = lifecycle.dispatch(principal=analyst, request_id=rid,
                                idempotency_key="dispatch-1")
    assert replay["idempotent_replay"] is True
    assert replay["dispatch"]["dispatch_id"] == first["dispatch"]["dispatch_id"]
    with pytest.raises(ShadowError, match="duplicate message"):
        lifecycle.dispatch(principal=analyst, request_id=rid,
                           idempotency_key="dispatch-2")


def test_evidence_substitution_after_approval_fails_closed(rig):
    lifecycle, store = rig["lifecycle"], rig["store"]
    rid, analyst, _ = run_to_state(rig, "APPROVED_SHADOW")
    row = store.execute(TENANT,
                        "SELECT request_json FROM action_state WHERE tenant_id=? AND request_id=?",
                        (TENANT, rid)).fetchone()
    bound = json.loads(row["request_json"])["evidence_ids"][0]
    # substitute the CONTENT behind the bound digest (id unchanged)
    with store.transaction() as conn:
        conn.execute("UPDATE ingest_events SET canonical_json=? "
                     "WHERE tenant_id=? AND digest=?",
                     ('{"tampered": true}', TENANT, bound))
    with pytest.raises(EvidenceBindingError):
        lifecycle.dispatch(principal=analyst, request_id=rid, idempotency_key="tampered")
    assert lifecycle.state_of(TENANT, rid) == "EVIDENCE_FAILED"


def test_external_execution_is_provably_false_everywhere(rig):
    lifecycle = rig["lifecycle"]
    rid, analyst, _ = run_to_state(rig, "OUTCOME_RECORDED")
    row = rig["store"].execute(
        TENANT, "SELECT dispatch_json FROM action_state WHERE tenant_id=? AND request_id=?",
        (TENANT, rid)).fetchone()
    dispatch = json.loads(row["dispatch_json"])
    assert dispatch["external_execution"] is False
    assert dispatch["external_executor_state"]["enabled"] is False
    assert "refused" in dispatch["external_executor_state"]["fail_closed_proof"]


def test_outcome_carries_resolver_identity_and_decision_quality(rig):
    rid, analyst, _ = run_to_state(rig, "OUTCOME_RECORDED")
    row = rig["store"].execute(
        TENANT, "SELECT outcome_json FROM action_state WHERE tenant_id=? AND request_id=?",
        (TENANT, rid)).fetchone()
    outcome = json.loads(row["outcome_json"])
    assert outcome["resolver_id"] == "user-analyst"
    assert outcome["decision_quality"]["abs_error_days"] == 1.5
    assert outcome["decision_quality"]["label"] == "SHADOW_FIXTURE_CALIBRATION"


def test_replay_verifies_the_whole_trail(rig):
    lifecycle = rig["lifecycle"]
    rid, analyst, _ = run_to_state(rig, "OUTCOME_RECORDED")
    receipt = lifecycle.replay(principal=analyst, request_id=rid)
    assert receipt["verified"] is True
    assert set(receipt["checks"]) == {"evidence_binding", "audit_chain",
                                      "transition_legality", "dual_control",
                                      "signatures", "external_execution_false"}
    assert all(receipt["checks"].values())
    assert lifecycle.state_of(TENANT, rid) == "REPLAY_VERIFIED"


def test_evidence_room_export_is_complete_and_content_addressed(rig):
    lifecycle = rig["lifecycle"]
    rid, analyst, _ = run_to_state(rig, "REPLAY_VERIFIED")
    # export is an operator/auditor permission — analysts are refused
    with pytest.raises(AuthorizationError):
        lifecycle.export_evidence_room(principal=analyst, request_id=rid,
                                       object_store=rig["objects"])
    operator = rig["principal"]("user-operator", ["operator"])
    export = lifecycle.export_evidence_room(principal=operator, request_id=rid,
                                            object_store=rig["objects"])
    data = rig["objects"].get(export["object_digest"])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        assert {"request.json", "approval.json", "dispatch.json", "outcome.json",
                "replay.json", "evidence_records.json", "audit_chain.json",
                "audit_head_commitment.json", "timeline.json",
                "MANIFEST.json"} <= names
        manifest = json.loads(archive.read("MANIFEST.json"))
        assert manifest["external_execution"] is False
        replay = json.loads(archive.read("replay.json"))
        assert replay["verified"] is True
