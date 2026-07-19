import pytest

from eagle_eye.voi import VoiError, sign_loss_function, value_of_information

ACTIONS = {
    "wait_incumbent": {"delta": 0.0, "var": 0.001},
    "expedite_shipment": {"delta": -0.45, "var": 0.01},
    "activate_alternate": {"delta": -0.30, "var": 0.05},
}


def _loss(**overrides):
    base = {
        "spec": "loss/1.0",
        "exposure_rate_per_day_usd": 9000.0,
        "intervention_cost_usd": {"wait_incumbent": 0.0, "expedite_shipment": 45000.0,
                                   "activate_alternate": 30000.0},
    }
    base.update(overrides)
    return sign_loss_function(base)


def _voi(**overrides):
    kwargs = dict(posterior_mean=2.6, posterior_var=0.08, sigma2=0.09,
                  actions=ACTIONS, loss=_loss(), signal_sd=0.30,
                  signal_cost_usd=500.0, waiting_cost_usd=2000.0)
    kwargs.update(overrides)
    return value_of_information(**kwargs)


def test_zero_information_signal_has_no_value():
    result = _voi(signal_sd=50.0)
    assert result["expected_value_of_information_usd"] < 200.0
    assert result["recommended_wait_or_act"] == "act_now"


def test_perfect_signal_maximizes_information():
    near_perfect = _voi(signal_sd=0.01)
    noisy = _voi(signal_sd=0.5)
    assert near_perfect["expected_value_of_information_usd"] > noisy["expected_value_of_information_usd"]
    assert near_perfect["expected_value_of_information_usd"] > 0


def test_signal_more_expensive_than_value_means_act_now():
    result = _voi(signal_cost_usd=10_000_000.0)
    assert result["recommended_wait_or_act"] == "act_now"
    assert result["net_value_of_waiting_usd"] < 0


def test_waiting_cost_dominates():
    result = _voi(waiting_cost_usd=10_000_000.0)
    assert result["recommended_wait_or_act"] == "act_now"


def test_changed_loss_function_changes_decision():
    cheap_expedite = _voi(loss=_loss(intervention_cost_usd={
        "wait_incumbent": 0.0, "expedite_shipment": 100.0, "activate_alternate": 30000.0}))
    expensive_expedite = _voi(loss=_loss(intervention_cost_usd={
        "wait_incumbent": 0.0, "expedite_shipment": 500000.0, "activate_alternate": 500000.0}))
    assert cheap_expedite["decision_now"] == "expedite_shipment"
    assert expensive_expedite["decision_now"] == "wait_incumbent"
    assert cheap_expedite["loss_function_hash"] != expensive_expedite["loss_function_hash"]


def test_unstable_posterior_raises_information_value():
    unstable = _voi(posterior_var=0.6)
    stable = _voi(posterior_var=0.005)
    assert unstable["expected_value_of_information_usd"] > stable["expected_value_of_information_usd"]


def test_missing_signal_likelihood_rejected():
    with pytest.raises(VoiError, match="signal likelihood"):
        _voi(signal_sd=0.0)


def test_policy_forbidden_delay_is_explicit():
    result = _voi(signal_sd=0.01, signal_cost_usd=0.0, waiting_cost_usd=0.0, delay_allowed=False)
    assert result["recommended_wait_or_act"] == "act_now_policy_forbids_delay"


def test_tampered_or_unsigned_loss_rejected():
    loss = _loss()
    loss["exposure_rate_per_day_usd"] = 1.0  # tamper after signing
    with pytest.raises(VoiError, match="tampered"):
        _voi(loss=loss)
    with pytest.raises(VoiError, match="signed"):
        _voi(loss={"exposure_rate_per_day_usd": 9000.0, "intervention_cost_usd": {}})


def test_non_normal_posterior_is_labeled_model_conditional():
    result = _voi(posterior_is_normal=False)
    assert result["exact_or_approximate"] == "MODEL_CONDITIONAL_ESTIMATE"
    exact = _voi()
    assert exact["exact_or_approximate"] == "exact"
    assert len(result["receipt_hash"]) == 64
