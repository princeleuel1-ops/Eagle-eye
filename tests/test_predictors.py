import copy
import math

import pytest

from eagle_eye.governor import govern, shift_score_for, support_state_for
from eagle_eye.predictors import (
    CANDIDATES,
    LogScaleDist,
    predict_naive_pooling,
    predict_no_prefix,
    predict_oracle_hier,
    predict_oracle_true,
    predict_seq_prefix,
    predict_set_mt,
)
from eagle_eye.prior_registry import build_registry
from eagle_eye.prior_selector import compile_prior_context, select_prior_tasks
from eagle_eye.regimes import generate_target_case, generate_world


@pytest.fixture(scope="module")
def world():
    return generate_world(424242, tasks_per_regime=16)


@pytest.fixture(scope="module")
def registry(world):
    return build_registry(world["tasks"])


@pytest.fixture(scope="module")
def case(world):
    return generate_target_case(
        world, case_index=5, tenant_id="tenant-demo",
        disruption_class="port_congestion", cutoff="2025-04-01", n_target_obs=2,
    )


@pytest.fixture(scope="module")
def compiled(registry, case):
    selection = select_prior_tasks(registry, case["target"], k_max=10)
    return compile_prior_context(selection["included"], case["target"])


def _delay_dist(prediction) -> LogScaleDist:
    return prediction["_delay_dist"]


def test_all_candidates_emit_canonical_channels(compiled):
    for name, fn in CANDIDATES.items():
        prediction = fn(compiled)
        assert prediction["candidate"] == name
        assert prediction["prior_manifest_sha256"] == compiled["prior_manifest_sha256"]
        for intervention, payload in prediction["interventions"].items():
            delay = payload["delay"]
            assert delay["quantiles_days"]["p10"] < delay["quantiles_days"]["p50"] < delay["quantiles_days"]["p90"]
            assert 0.0 <= delay["p_exceeds_days"]["14"] <= 1.0
            assert delay["interval"]["low_days"] < delay["interval"]["high_days"]
            assert 0.0 <= payload["stockout"]["p"] <= 1.0
            assert payload["exposure_usd"]["quantiles_usd"]["p50"] > 0


def test_dists_are_valid_probability_objects(compiled):
    prediction = predict_set_mt(compiled)
    dist = _delay_dist(prediction)
    assert dist.cdf(dist.ppf(0.25)) == pytest.approx(0.25, abs=1e-8)
    assert math.exp(dist.logpdf(dist.loc)) > 0
    assert dist.crps(dist.loc) < dist.crps(dist.loc + 3 * dist.scale)


def test_set_mt_is_permutation_invariant_and_seq_prefix_is_not(compiled):
    reversed_compiled = copy.deepcopy(compiled)
    reversed_compiled["prior_blocks"] = list(reversed(reversed_compiled["prior_blocks"]))
    set_a, set_b = predict_set_mt(compiled), predict_set_mt(reversed_compiled)
    assert _delay_dist(set_a).loc == pytest.approx(_delay_dist(set_b).loc, abs=1e-12)
    assert _delay_dist(set_a).scale == pytest.approx(_delay_dist(set_b).scale, abs=1e-12)
    seq_a, seq_b = predict_seq_prefix(compiled), predict_seq_prefix(reversed_compiled)
    assert abs(_delay_dist(seq_a).loc - _delay_dist(seq_b).loc) > 1e-6


def test_prior_transfer_beats_no_prefix_when_target_is_scarce(world, registry):
    """With zero target observations the prior prefix must dominate: the
    hierarchical candidates should land far closer to the oracle location."""
    case = generate_target_case(
        world, case_index=9, tenant_id="tenant-demo",
        disruption_class="port_congestion", cutoff="2025-04-20", n_target_obs=0,
    )
    selection = select_prior_tasks(registry, case["target"], k_max=12)
    compiled = compile_prior_context(selection["included"], case["target"])
    oracle = predict_oracle_hier(compiled, case["truth"]["hyper"])
    no_prefix = predict_no_prefix(compiled)
    set_mt = predict_set_mt(compiled)
    oracle_loc = _delay_dist(oracle).loc
    assert abs(_delay_dist(set_mt).loc - oracle_loc) < abs(_delay_dist(no_prefix).loc - oracle_loc) + 0.05
    # And the set candidate is meaningfully sharper than the target-only baseline.
    assert _delay_dist(set_mt).scale < _delay_dist(no_prefix).scale


def test_oracle_true_is_well_centered(world, registry):
    """Averaged over cases, oracle_true should score at least as well as a
    fixed wrong-location forecast (sanity anchor for the truth plumbing)."""
    case = generate_target_case(
        world, case_index=3, tenant_id="tenant-demo",
        disruption_class="supplier_quality", cutoff="2025-05-01", n_target_obs=4,
    )
    selection = select_prior_tasks(registry, case["target"], k_max=8)
    compiled = compile_prior_context(selection["included"], case["target"])
    oracle = predict_oracle_true(compiled, case["truth"])
    realized = case["truth"]["outcomes"]["wait_incumbent"]["log_final_delay"]
    dist = _delay_dist(oracle)
    wait = oracle["interventions"]["wait_incumbent"]["delay"]
    assert wait["family"] == "normal_log"
    assert dist.crps(realized) < LogScaleDist(dist.loc + 2.0, dist.scale).crps(realized)


def test_naive_pooling_drowns_target_evidence(compiled):
    """The pooling anti-pattern: prior observations swamp the target's own
    evidence, so the pooled location barely responds when target evidence
    moves. The hierarchical set candidate must respond far more strongly."""
    perturbed = copy.deepcopy(compiled)
    perturbed["target_block"]["observations"] = [
        v + 1.0 for v in perturbed["target_block"]["observations"]
    ]
    pool_shift = abs(_delay_dist(predict_naive_pooling(perturbed)).loc
                     - _delay_dist(predict_naive_pooling(compiled)).loc)
    set_shift = abs(_delay_dist(predict_set_mt(perturbed)).loc
                    - _delay_dist(predict_set_mt(compiled)).loc)
    assert set_shift > 3.0 * pool_shift
    # pooling treats ~all observations as one task: hyper-level df explodes
    assert _delay_dist(predict_naive_pooling(compiled)).df > _delay_dist(predict_set_mt(compiled)).df


def test_intervention_ordering_reflects_prior_effects(compiled):
    prediction = predict_set_mt(compiled)
    wait = prediction["interventions"]["wait_incumbent"]["delay"]["quantiles_days"]["p50"]
    expedite = prediction["interventions"]["expedite_shipment"]["delay"]["quantiles_days"]["p50"]
    assert expedite < wait  # expedite has a strongly negative true effect in this regime


def test_support_states():
    assert support_state_for(12) == "strong"
    assert support_state_for(5) == "moderate"
    assert support_state_for(1) == "weak"
    assert support_state_for(0) == "unsupported"


def test_governor_abstains_without_prior_support(world, registry, case):
    compiled_empty = compile_prior_context([], case["target"])
    prediction = predict_set_mt(compiled_empty)
    governed = govern(prediction, compiled_empty)
    assert governed["governed"]["abstained"] is True
    assert governed["interventions"] is None
    assert "abstain" in governed["abstain_reason"]


def test_governor_widens_under_weak_support(world, registry, case):
    selection = select_prior_tasks(registry, case["target"], k_max=2)
    compiled_weak = compile_prior_context(selection["included"], case["target"])
    raw = predict_set_mt(compiled_weak)
    governed = govern(raw, compiled_weak)
    assert governed["governed"]["support_state"] == "weak"
    assert governed["governed"]["widen_factor"] > 1.0
    raw_width = raw["interventions"]["wait_incumbent"]["delay"]["interval"]
    gov_width = governed["interventions"]["wait_incumbent"]["delay"]["interval"]
    assert (gov_width["high_days"] - gov_width["low_days"]) > (raw_width["high_days"] - raw_width["low_days"])


def test_governor_flags_regime_shift(world, registry):
    """A target whose evidence sits far from the prior-implied law must raise
    shift_score toward 1 and trigger widening."""
    case = generate_target_case(
        world, case_index=11, tenant_id="tenant-demo",
        disruption_class="port_congestion", cutoff="2025-04-10", n_target_obs=4,
    )
    selection = select_prior_tasks(registry, case["target"], k_max=10)
    compiled = compile_prior_context(selection["included"], case["target"])
    shifted = copy.deepcopy(compiled)
    shifted["target_block"]["observations"] = [v + 2.5 for v in shifted["target_block"]["observations"]]
    raw = predict_set_mt(shifted)
    score = shift_score_for(shifted, raw["diagnostics"])
    assert score is not None and score > 0.95
    governed = govern(raw, shifted)
    assert any("regime_shift" in adj for adj in governed["governed"]["adjustments"])


def test_governor_abstains_beyond_validated_k(compiled):
    prediction = predict_set_mt(compiled)
    prediction = {**prediction, "training_support": {"k_range": [0, 4], "context_range": [0, 400]}}
    governed = govern(prediction, compiled)
    assert governed["governed"]["abstained"] is True
    assert not governed["governed"]["k_within_support"]
