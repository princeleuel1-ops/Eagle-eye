import hashlib
import json
from pathlib import Path

import pytest

from eagle_eye.prediction_court import (
    build_development_suite,
    build_holdout_suite,
    contamination_check,
    run_prediction_court,
)


@pytest.fixture(scope="module")
def court(tmp_path_factory):
    out = tmp_path_factory.mktemp("court-a")
    receipt = run_prediction_court(out)
    return {"receipt": receipt, "dir": out}


def _decision(receipt, name):
    return next(d for d in receipt["decisions"] if d["candidate"] == name)


def test_suites_are_sealed_and_uncontaminated(court):
    receipt = court["receipt"]
    assert receipt["contamination"]["contamination_detected"] is False
    assert receipt["contamination"]["world_seeds_distinct"] is True
    for seal_key in ("development_seal", "holdout_seal"):
        seal = receipt[seal_key]
        body = Path(seal["cases_path"]).read_bytes()
        assert hashlib.sha256(body).hexdigest() == seal["cases_sha256"]
        truth_body = Path(seal["truth_path"]).read_bytes()
        assert hashlib.sha256(truth_body).hexdigest() == seal["truth_sha256"]
        # Predictor-visible case files never contain hidden truth.
        assert b'"theta"' not in body
        assert b'"outcomes"' not in body


def test_leakage_battery_all_defended(court):
    leak = court["receipt"]["leakage"]
    assert leak["future_task_refused"] is True
    assert leak["foreign_tenant_refused"] is True
    assert leak["selector_no_future_tasks"] is True
    assert leak["selector_no_foreign_tenants"] is True
    assert leak["all_defended"] is True


def test_governed_candidate_is_promoted(court):
    receipt = court["receipt"]
    assert _decision(receipt, "governed_set_mt")["status"] == "promote"
    assert receipt["proofs"]["beneficial_candidate_promoted"] is True


def test_attractive_regression_is_rejected_with_proof(court):
    receipt = court["receipt"]
    decision = _decision(receipt, "seq_prefix_overfit")
    assert decision["status"] == "reject"
    dev_overfit = receipt["evaluations"]["seq_prefix_overfit"]["development"]["metrics"]["nll"]
    dev_baseline = receipt["evaluations"]["no_prefix"]["development"]["metrics"]["nll"]
    assert dev_overfit < dev_baseline  # it really was attractive on development
    assert receipt["proofs"]["attractive_regression_rejected"] is True


def test_pooling_and_climatology_fail_proper_scoring(court):
    receipt = court["receipt"]
    assert "proper_scoring_improved" in _decision(receipt, "naive_pooling")["reasons"]
    assert "proper_scoring_improved" in _decision(receipt, "climatology")["reasons"]


def test_sequential_candidates_fail_permutation_gate(court):
    receipt = court["receipt"]
    assert "permutation_within_tolerance" in _decision(receipt, "seq_prefix")["reasons"]
    metrics = receipt["evaluations"]
    assert metrics["seq_prefix"]["holdout"]["metrics"]["permutation_spread_max"] > \
        metrics["set_mt"]["holdout"]["metrics"]["permutation_spread_max"]


def test_ungoverned_set_mt_fails_only_out_of_support_refusal(court):
    decision = _decision(court["receipt"], "set_mt")
    assert decision["status"] == "reject"
    assert decision["reasons"] == ["out_of_support_refused"]


def test_prior_transfer_effect_is_large_and_measured(court):
    metrics = court["receipt"]["evaluations"]
    set_mt = metrics["set_mt"]["holdout"]["metrics"]
    baseline = metrics["no_prefix"]["holdout"]["metrics"]
    assert set_mt["nll"] < baseline["nll"] - 0.15
    assert set_mt["crps"] < baseline["crps"]
    assert set_mt["kl_to_oracle"] < baseline["kl_to_oracle"] / 5.0
    assert set_mt["intervention_regret_days"] < baseline["intervention_regret_days"] / 2.0


def test_negative_transfer_is_measured(court):
    governed = court["receipt"]["evaluations"]["governed_set_mt"]["holdout"]["metrics"]
    assert governed["nll_unrelated_priors"] is not None
    assert governed["nll_unrelated_priors"] > governed["nll"]


def test_governor_abstains_on_all_k_probes(court):
    governed = court["receipt"]["evaluations"]["governed_set_mt"]["holdout"]
    assert governed["abstentions_probe"] == 2
    assert governed["abstentions_standard"] == 0


def test_receipt_is_deterministic_across_runs(court, tmp_path_factory):
    second = run_prediction_court(tmp_path_factory.mktemp("court-b"))
    first = court["receipt"]
    assert second["court_receipt_id"] == first["court_receipt_id"]
    assert second["development_sha256"] == first["development_sha256"]
    assert second["holdout_sha256"] == first["holdout_sha256"]
    assert second["evaluations"]["set_mt"]["holdout"]["metrics"] == \
        first["evaluations"]["set_mt"]["holdout"]["metrics"]


def test_contamination_detector_fires_on_shared_seed():
    same = build_development_suite(99)
    clone = build_holdout_suite(99)
    # different plans, same world seed -> must at minimum flag seed reuse
    result = contamination_check(same, clone)
    assert result["contamination_detected"] is True
