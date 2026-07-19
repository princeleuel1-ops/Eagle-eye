import copy

import pytest

from eagle_eye.outcome_resolution import PredictionLedger, ResolutionError
from eagle_eye.posterior_engine import attach_posterior_intelligence, build_demo_registry, build_demo_target
from eagle_eye.prior_registry import validate_task


@pytest.fixture(scope="module")
def registry():
    return build_demo_registry()


@pytest.fixture(scope="module")
def court_stub(registry):
    return {
        "court_receipt_id": "pcourt-or-test", "development_sha256": "d" * 64, "holdout_sha256": "h" * 64,
        "registry_manifest_sha256": registry["manifest_sha256"],
        "decisions": [{"candidate": "governed_set_mt", "status": "promote", "reasons": []}],
        "evaluations": {"governed_set_mt": {"holdout": {"metrics": {
            "nll": 0.77, "crps": 0.33, "coverage80": 0.9, "nll_temporal_ood": 0.44,
            "permutation_spread_max": 0.0}}}},
    }


POLICY_REGISTRY = {"policy:hold-and-observe/1": {"follow_prob": 0.7, "authenticated": True,
                                                  "record_hash": "r" * 64}}


@pytest.fixture()
def ledger(registry, court_stub):
    ledger = PredictionLedger("tenant-demo", policy_registry=POLICY_REGISTRY)
    fixture = {
        "events": [{"id": "evt-or", "supplier_id": "sup-1", "severity": 0.6, "source_id": "src-1"}],
        "purchase_orders": [{"id": "PO-17", "supplier_id": "sup-1", "product_id": "p", "value": 200000}],
        "components": [{"id": "c1", "supplier_id": "sup-1", "product_id": "p"}],
    }
    run = {"run_id": "r", "mode": "FIXTURE"}
    target = build_demo_target(fixture)
    attach_posterior_intelligence(run, registry=registry, target=target, court_receipt=court_stub)
    committed = ledger.commit_prediction(run["posterior_intelligence"], champion_id="champ-0",
                                         policy_release_hash="pol" + "0" * 61, resource_scope="scope:po17")
    return ledger, committed


def _resolution(committed, **overrides):
    base = {
        "prediction_id": committed["prediction_id"],
        "prediction_distribution_hash": committed["prediction_distribution_hash"],
        "policy_release_hash": committed["policy_release_hash"],
        "tenant_id": "tenant-demo",
        "resource_scope": "scope:po17",
        "outcome_observed_at": "2025-05-20",
        "outcome_value": 2.62,
        "outcome_source": "authorized_synthetic_truth",
        "intervention_taken": "wait_incumbent",
        "acting_policy": "policy:hold-and-observe/1",
        "recommendation_propensity": 0.30,
        "observed": {"final_delay_days": 13.7, "stockout": False, "recovery_days": 19.0,
                      "exposure_usd": 123000.0, "intervention_result": None},
        "entity_refs": {"supplier_id": "sup-1", "component_id": "c1", "lane": "asia-us-west",
                         "region": "APAC", "exposure_rate_per_day_usd": 9000.0},
        "confounders": {"schema_version": "confounders/1.0", "vector": {"lane": "asia-us-west"}},
        "authorization_receipt": "approval-test",
    }
    base.update(overrides)
    return base


def test_happy_path_scores_against_committed_distribution(ledger):
    ledger_obj, committed = ledger
    row = ledger_obj.resolve(_resolution(committed))
    assert row["score"]["nll"] > 0 and row["score"]["crps"] > 0
    assert 0.0 <= row["score"]["pit"] <= 1.0
    assert row["eligibility_for_registry"] is True  # intervention_free path
    assert row["off_policy"]["state"] in ("CHECKED", "IDENTIFIABLE_UNDER_STATED_ASSUMPTIONS")
    assert row["off_policy"]["checks"]["propensity_recomputed_matches_claim"] is True
    assert ledger_obj.verify_chain()
    task = ledger_obj.grow_registry_task(row)
    validate_task(task)
    assert task["as_of_end"] == "2025-05-20"
    assert task["sources"][0]["resolution_hash"] == row["current_audit_hash"]
    # STRICT growth: every realized field comes from the recorded observation
    assert task["realized"]["final_delay_days"] == 13.7
    assert task["realized"]["stockout"] is False
    assert task["realized"]["intervention_success"] is None  # unknown stays unknown
    assert task["entity_refs"]["supplier_id"] == "sup-1"


def test_rejects_unknown_prediction_and_cross_tenant_and_scope(ledger):
    ledger_obj, committed = ledger
    with pytest.raises(ResolutionError, match="no committed prediction"):
        ledger_obj.resolve(_resolution(committed, prediction_id="pred-doesnotexist"))
    with pytest.raises(ResolutionError, match="tenant"):
        ledger_obj.resolve(_resolution(committed, tenant_id="tenant-mallory"))
    with pytest.raises(ResolutionError, match="scope"):
        ledger_obj.resolve(_resolution(committed, resource_scope="scope:other"))
    with pytest.raises(ResolutionError, match="policy release"):
        ledger_obj.resolve(_resolution(committed, policy_release_hash="x" * 64))


def test_rejects_mutated_prediction_and_tampered_hash(ledger):
    ledger_obj, committed = ledger
    pred = ledger_obj.predictions[committed["prediction_id"]]
    original = copy.deepcopy(pred["block"])
    pred["block"]["interventions"]["wait_incumbent"]["delay"]["loc"] += 0.4
    with pytest.raises(ResolutionError, match="changed after commitment"):
        ledger_obj.resolve(_resolution(committed))
    pred["block"] = original
    with pytest.raises(ResolutionError, match="tampered distribution"):
        ledger_obj.resolve(_resolution(committed, prediction_distribution_hash="f" * 64))


def test_rejects_time_travel_and_leakage(ledger):
    ledger_obj, committed = ledger
    with pytest.raises(ResolutionError, match="predates"):
        ledger_obj.resolve(_resolution(committed, outcome_observed_at="2025-01-01"))
    with pytest.raises(ResolutionError, match="leakage"):
        ledger_obj.resolve(_resolution(committed, features_used=["post_outcome"]))


def test_duplicate_and_revision_discipline(ledger):
    ledger_obj, committed = ledger
    first = ledger_obj.resolve(_resolution(committed))
    with pytest.raises(ResolutionError, match="duplicate outcome"):
        ledger_obj.resolve(_resolution(committed))
    revised = ledger_obj.resolve(_resolution(committed, resolution_status="REVISED", outcome_value=2.70))
    assert revised["revision_of"] == first["current_audit_hash"]
    assert len(ledger_obj.resolutions) == 2  # append, never overwrite
    assert ledger_obj.verify_chain()


def test_unknown_intervention_is_visible_but_ineligible(ledger):
    ledger_obj, committed = ledger
    row = ledger_obj.resolve(_resolution(committed, intervention_taken=None,
                                         recommendation_propensity=None))
    assert row["intervention_status"] == "unknown_intervention"
    assert row["eligibility_for_registry"] is False
    assert "unknown_intervention" in row["eligibility_reason"]
    assert row["off_policy"]["state"] in ("LOGGED", "NOT_IDENTIFIABLE")


def test_forged_propensity_is_not_identifiable(ledger):
    """Caller claims 1.0 but the authenticated policy record implies 0.7 for a
    followed recommendation -> forged -> NOT_IDENTIFIABLE (audit blocker 6)."""
    ledger_obj, committed = ledger
    row = ledger_obj.resolve(_resolution(
        committed, intervention_taken="expedite_shipment",
        recommendation_propensity=1.0))
    assert row["off_policy"]["checks"]["caller_propensity_forged"] is True
    assert row["off_policy"]["state"] == "NOT_IDENTIFIABLE"
    assert row["eligibility_for_registry"] is False
    assert row["off_policy"]["usable_for"] == "predictive_monitoring_only"


def test_unlogged_policy_is_not_identifiable(ledger):
    ledger_obj, committed = ledger
    row = ledger_obj.resolve(_resolution(committed, intervention_taken="expedite_shipment",
                                         acting_policy="policy:unknown/9",
                                         recommendation_propensity=0.7))
    assert row["off_policy"]["state"] == "NOT_IDENTIFIABLE"
    assert row["eligibility_for_registry"] is False


def test_source_hash_mismatch_rejected(ledger):
    ledger_obj, committed = ledger
    with pytest.raises(ResolutionError, match="source hash mismatch"):
        ledger_obj.resolve(_resolution(committed,
                                       outcome_source_payload={"x": 1},
                                       outcome_source_hash="f" * 64))


def test_growth_refused_for_foreign_row(ledger):
    ledger_obj, committed = ledger
    row = ledger_obj.resolve(_resolution(committed))
    import copy as _copy
    forged = _copy.deepcopy(row)
    forged["current_audit_hash"] = "a" * 64
    with pytest.raises(ResolutionError, match="not present in this ledger"):
        ledger_obj.grow_registry_task(forged)


def test_missing_and_disputed_preserved_explicitly(ledger):
    ledger_obj, committed = ledger
    row = ledger_obj.resolve(_resolution(committed, resolution_status="MISSING", outcome_value=None))
    assert row["resolution_status"] == "MISSING"
    assert row["score"] is None
    assert row["eligibility_for_registry"] is False
    assert ledger_obj.verify_chain()


def test_chain_tamper_detection(ledger):
    ledger_obj, committed = ledger
    ledger_obj.resolve(_resolution(committed))
    ledger_obj.resolutions[0]["outcome_value_micro"] = 999999
    assert ledger_obj.verify_chain() is False


def test_intervention_affected_needs_measured_identifiability(ledger):
    """Correct propensity for a followed recommendation is 0.7 (policy record);
    with insufficient accumulated ESS the state is CHECKED, and the
    intervention-affected outcome is NOT eligible - measured, not asserted."""
    ledger_obj, committed = ledger
    rec = ledger_obj.predictions[committed["prediction_id"]]["block"]["recommendation"]["recommended_intervention"]
    row = ledger_obj.resolve(_resolution(committed, intervention_taken=rec,
                                         recommendation_propensity=0.7))
    assert row["intervention_status"] == ("intervention_free" if rec == "wait_incumbent" else "intervention_affected")
    assert row["off_policy"]["checks"]["propensity_recomputed_matches_claim"] is True
    assert row["off_policy"]["state"] in ("CHECKED", "IDENTIFIABLE_UNDER_STATED_ASSUMPTIONS")
    if row["intervention_status"] == "intervention_affected" and row["off_policy"]["state"] == "CHECKED":
        assert row["eligibility_for_registry"] is False
