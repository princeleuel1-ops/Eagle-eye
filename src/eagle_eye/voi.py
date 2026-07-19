"""Value of information: is it worth waiting for one more signal?

Exact preposterior analysis for the conjugate Normal case the engine already
uses on log-delay. The label 'exact' means exact under the implemented model
(normal posterior over the task latent, known observation sd, signed loss);
any t-distributed posterior is normal-approximated and labeled
MODEL_CONDITIONAL_ESTIMATE. Dollar values are never emitted without the signed
loss function hash, assumptions, uncertainty range, and a receipt hash.
"""

from __future__ import annotations

import math
from typing import Any

from .prior_registry import canonical_bytes, sha256_hex
from .stats import norm_pdf

VOI_SPEC = "eagle-eye-value-of-information/1.0"
GRID_N = 161
GRID_SPAN = 5.0


class VoiError(ValueError):
    pass


def sign_loss_function(loss: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in loss.items() if key != "loss_function_hash"}
    return {**body, "loss_function_hash": sha256_hex(canonical_bytes(body))}


def _expected_loss(posterior_mean: float, posterior_var: float, sigma2: float,
                   actions: dict[str, dict[str, float]], loss: dict[str, Any]) -> tuple[str, float, dict[str, float]]:
    """Expected loss per action under predictive y ~ N(mean+delta, var+d_var+sigma2).

    loss = exposure_rate * E[exp(y)] + intervention_cost  (lognormal mean, exact).
    """
    rate = loss["exposure_rate_per_day_usd"]
    per_action: dict[str, float] = {}
    for name, cfg in actions.items():
        mu = posterior_mean + cfg["delta"]
        var = posterior_var + cfg["var"] + sigma2
        expected_days = math.exp(mu + 0.5 * var)
        per_action[name] = rate * expected_days + loss["intervention_cost_usd"].get(name, 0.0)
    best = min(per_action, key=lambda n: (per_action[n], n))
    return best, per_action[best], per_action


def value_of_information(*, posterior_mean: float, posterior_var: float, sigma2: float,
                         actions: dict[str, dict[str, float]], loss: dict[str, Any],
                         signal_sd: float, signal_cost_usd: float, waiting_cost_usd: float,
                         decision_horizon_days: int = 7, delay_allowed: bool = True,
                         posterior_is_normal: bool = True) -> dict[str, Any]:
    """Exact (grid-quadrature) preposterior EVOI for one additional signal."""
    if "loss_function_hash" not in loss:
        raise VoiError("loss function must be signed (sign_loss_function)")
    body = {key: value for key, value in loss.items() if key != "loss_function_hash"}
    if sha256_hex(canonical_bytes(body)) != loss["loss_function_hash"]:
        raise VoiError("tampered loss function hash")
    if signal_sd <= 0:
        raise VoiError("missing or invalid signal likelihood (signal_sd must be > 0)")

    act_now, loss_now, per_action_now = _expected_loss(
        posterior_mean, posterior_var, sigma2, actions, loss)

    # Preposterior: observing y' ~ N(theta, signal_sd^2); theta ~ N(m, v).
    # Predictive of y': N(m, v + s2). Posterior after y': var v' = 1/(1/v + 1/s2),
    # mean m' = v'*(m/v + y'/s2). Expected min-loss after the signal by quadrature.
    s2 = signal_sd ** 2
    v = posterior_var
    v_post = 1.0 / (1.0 / v + 1.0 / s2) if v > 0 else 0.0
    pred_sd = math.sqrt(v + s2)
    lo, hi = posterior_mean - GRID_SPAN * pred_sd, posterior_mean + GRID_SPAN * pred_sd
    h = (hi - lo) / (GRID_N - 1)
    expected_after = 0.0
    weight_total = 0.0
    for i in range(GRID_N):
        y_prime = lo + i * h
        w = norm_pdf(y_prime, posterior_mean, pred_sd) * (0.5 if i in (0, GRID_N - 1) else 1.0)
        m_post = v_post * (posterior_mean / v + y_prime / s2) if v > 0 else posterior_mean
        _, best_loss, _ = _expected_loss(m_post, v_post, sigma2, actions, loss)
        expected_after += w * best_loss
        weight_total += w
    expected_after /= weight_total  # normalized quadrature (guards tail truncation)

    evoi = max(0.0, loss_now - expected_after)
    net = evoi - signal_cost_usd - waiting_cost_usd
    recommend = "wait_for_signal" if (net > 0 and delay_allowed) else "act_now"
    if not delay_allowed and net > 0:
        recommend = "act_now_policy_forbids_delay"
    exact = posterior_is_normal
    result = {
        "spec": VOI_SPEC,
        "decision_now": act_now,
        "expected_loss_now_usd": round(loss_now, 2),
        "per_action_expected_loss_usd": {k: round(x, 2) for k, x in per_action_now.items()},
        "candidate_signal": {"kind": "one_shipment_delay_signal", "signal_sd": signal_sd},
        "expected_loss_after_signal_usd": round(expected_after, 2),
        "signal_acquisition_cost_usd": signal_cost_usd,
        "waiting_cost_usd": waiting_cost_usd,
        "expected_value_of_information_usd": round(evoi, 2),
        "net_value_of_waiting_usd": round(net, 2),
        "recommended_wait_or_act": recommend,
        "decision_horizon_days": decision_horizon_days,
        "assumptions": [
            "posterior over task latent is Normal (t approximated by normal when df large)",
            "one additional signal y' ~ N(theta, signal_sd^2)",
            "loss = exposure_rate * E[delay_days] + intervention cost (lognormal mean, exact)",
        ],
        "model_class": "conjugate-normal-preposterior",
        "exact_or_approximate": "exact" if exact else "MODEL_CONDITIONAL_ESTIMATE",
        "uncertainty_note": "EVOI is conditional on the stated model and the signed loss; sensitivity: recompute with alternative loss multipliers before acting",
        "loss_function_hash": loss["loss_function_hash"],
    }
    result["receipt_hash"] = sha256_hex(canonical_bytes(result))
    return result
