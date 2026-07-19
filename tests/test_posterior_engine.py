import copy

import pytest

from eagle_eye.posterior_engine import (
    attach_posterior_intelligence,
    build_demo_registry,
    build_demo_target,
)


@pytest.fixture(scope="module")
def registry():
    return build_demo_registry()


@pytest.fixture(scope="module")
def fixture_payload():
    return {
        "events": [{"id": "evt-17", "supplier_id": "sup-apex", "severity": 0.62, "source_id": "src-9"}],
        "purchase_orders": [{"id": "PO-17", "supplier_id": "sup-apex", "product_id": "prod-2", "value": 180000}],
        "components": [{"id": "cmp-77", "supplier_id": "sup-apex", "product_id": "prod-2"}],
    }


@pytest.fixture(scope="module")
def court_receipt(registry):
    return {
        "court_receipt_id": "pcourt-engine-test",
        "development_sha256": "d" * 64,
        "holdout_sha256": "h" * 64,
        "registry_manifest_sha256": registry["manifest_sha256"],
        "decisions": [{"candidate": "governed_set_mt", "status": "promote", "reasons": []}],
        "evaluations": {"governed_set_mt": {"holdout": {"metrics": {
            "nll": 0.7707, "crps": 0.3324, "coverage80": 0.9048,
            "nll_temporal_ood": 0.4417, "permutation_spread_max": 0.0}}}},
    }


@pytest.fixture(scope="module")
def block(registry, fixture_payload, court_receipt):
    run = {"run_id": "run-x", "mode": "FIXTURE"}
    target = build_demo_target(fixture_payload)
    attach_posterior_intelligence(run, registry=registry, target=target, court_receipt=court_receipt)
    return run["posterior_intelligence"]


def test_demo_target_is_deterministic_and_fixture_grounded(fixture_payload):
    a = build_demo_target(fixture_payload)
    b = build_demo_target(fixture_payload)
    assert a == b
    assert a["entity_refs"]["purchase_order_id"] == "PO-17"
    assert all(obs["source_id"] == "src-9" for obs in a["observations"])
    assert all(obs["t"] <= a["as_of_cutoff"] for obs in a["observations"])


def test_block_carries_all_required_commitments(block):
    for field in (
        "predictive_distribution_commitment", "intervention_set_commitment",
        "prior_manifest_sha256", "calibration_receipt_sha256", "model_artifact_sha256",
        "K", "context_length", "training_support", "as_of_cutoff",
    ):
        assert field in block, field
    assert block["prior_registry"]["manifest_sha256"]
    assert block["selection_receipt"]["receipt_sha256"]
    assert block["benchmark_court"]["decision"] == "promote"
    assert len(block["predictive_distribution_commitment"]) == 64


def test_block_satisfies_cockpit_data_contract(block):
    """Every field path the cockpit panel dereferences must exist — this is
    the deterministic UI data gate behind the string-level semantic checks."""
    governed = block["governed"]
    assert governed["support_state"] in {"strong", "moderate", "weak", "unsupported"}
    assert governed["shift_score"] is None or 0.0 <= governed["shift_score"] <= 1.0
    assert isinstance(governed["adjustments"], list)
    rec = block["recommendation"]
    for field in ("recommended_intervention", "ranking", "expected_exposure_p50_usd",
                  "incumbent_exposure_p50_usd", "p_delay_exceeds_14_incumbent",
                  "p_delay_exceeds_14_recommended", "decision_basis", "what_would_falsify"):
        assert field in rec, field
    cal = block["calibration_receipt"]
    for field in ("nll_micro", "crps_micro", "coverage80_micro", "coverage_band_micro",
                  "court_receipt_id"):
        assert field in cal, field
    assert all(isinstance(v, (int, type(None), str, list)) for v in cal.values())
    for name, payload in block["interventions"].items():
        delay = payload["delay"]
        for q in ("p10", "p50", "p90"):
            assert delay["quantiles_days"][q] > 0
        assert delay["interval"]["low_days"] < delay["interval"]["high_days"]
        assert "14" in delay["p_exceeds_days"] and "21" in delay["p_exceeds_days"]
        assert 0.0 <= payload["stockout"]["p"] <= 1.0
        assert payload["exposure_usd"]["quantiles_usd"]["p50"] > 0
        assert payload["recovery_days"]["quantiles_days"]["p50"] > 0
        assert "effect_supported" in payload


def test_recommendation_ranking_is_exposure_ordered(block):
    ranking = block["recommendation"]["ranking"]
    medians = [block["interventions"][name]["exposure_usd"]["quantiles_usd"]["p50"]
               for name in ranking]
    assert medians == sorted(medians)
    assert block["recommendation"]["recommended_intervention"] == ranking[0]


def test_engine_is_deterministic(registry, fixture_payload, court_receipt):
    runs = []
    for _ in range(2):
        run = {"run_id": "run-x", "mode": "FIXTURE"}
        target = build_demo_target(fixture_payload)
        attach_posterior_intelligence(run, registry=registry, target=target,
                                      court_receipt=court_receipt)
        runs.append(run["posterior_intelligence"])
    assert runs[0] == runs[1]


def test_engine_refuses_non_governed_candidates(registry, fixture_payload, court_receipt):
    run = {"run_id": "run-x", "mode": "FIXTURE"}
    target = build_demo_target(fixture_payload)
    with pytest.raises(ValueError, match="governed"):
        attach_posterior_intelligence(run, registry=registry, target=target,
                                      court_receipt=court_receipt, candidate="set_mt")


def test_no_hidden_truth_leaks_into_block(block):
    text = str(block)
    assert "theta" not in text
    assert "regime_id_hidden" not in text
    assert "p_stockout" not in text
