"""Support and shift governor: fail closed or visibly downgrade confidence.

Wraps any candidate's prediction with:
  support_state   strong | moderate | weak | unsupported
  shift_score     [0,1] discrepancy between target evidence and prior-implied
                  predictive (2*Phi(|z|)-1); null when no target evidence
  actions         widen (scale inflation, recorded), abstain (no numbers)

The governor never silently improves a prediction; it can only widen, label,
or abstain. Every adjustment is recorded in the governed receipt.
"""

from __future__ import annotations

import math
from typing import Any

from .predictors import INTERVENTIONS, LogScaleDist, _package
from .stats import norm_cdf

GOVERNOR_RELEASE = "shift-support-governor/1.0"

WIDEN_WEAK = 1.35
WIDEN_SHIFT = 1.50
SHIFT_SUSPECT = 0.80


def support_state_for(k: int) -> str:
    if k >= 8:
        return "strong"
    if k >= 3:
        return "moderate"
    if k >= 1:
        return "weak"
    return "unsupported"


def shift_score_for(compiled: dict[str, Any], diagnostics: dict[str, Any]) -> float | None:
    """z-discrepancy of target evidence against the prior-implied signal law."""
    target_obs = compiled["target_block"]["observations"]
    if not target_obs or "m_hat" not in diagnostics:
        return None
    n = len(target_obs)
    ybar = sum(target_obs) / n
    tau2 = diagnostics.get("tau2", 0.09)
    sigma2 = diagnostics.get("sigma2", 0.09)
    spread = math.sqrt(tau2 + sigma2 / n)
    z = abs(ybar - diagnostics["m_hat"]) / max(1e-9, spread)
    return round(2.0 * norm_cdf(z) - 1.0, 6)


def govern(prediction: dict[str, Any], compiled: dict[str, Any], *,
           widen_weak: float = WIDEN_WEAK, widen_shift: float = WIDEN_SHIFT,
           shift_suspect: float = SHIFT_SUSPECT) -> dict[str, Any]:
    """Apply the governor to a raw candidate prediction (pure function).

    Threshold overrides exist ONLY for the whitelisted evolution mutation
    surface; defaults preserve the promoted release behavior exactly.
    """
    k = prediction["K"]
    support = support_state_for(k)
    training = prediction["training_support"]
    k_ok = training["k_range"][0] <= k <= training["k_range"][1]
    ctx_ok = training["context_range"][0] <= prediction["context_length"] <= training["context_range"][1]
    shift = shift_score_for(compiled, prediction.get("diagnostics", {}))

    adjustments: list[str] = []
    abstain = False
    widen = 1.0
    if not k_ok or not ctx_ok:
        abstain = True
        adjustments.append("abstain_out_of_validated_support")
    if support == "unsupported":
        abstain = True
        adjustments.append("abstain_no_prior_support")
    if support == "weak" and not abstain:
        widen *= widen_weak
        adjustments.append(f"widen_weak_support_x{widen_weak}")
    if shift is not None and shift >= shift_suspect and not abstain:
        widen *= widen_shift
        adjustments.append(f"widen_regime_shift_x{widen_shift}")

    governed = {
        "governor_release": GOVERNOR_RELEASE,
        "support_state": support,
        "shift_score": shift,
        "k_within_support": k_ok,
        "context_within_support": ctx_ok,
        "abstained": abstain,
        "widen_factor": round(widen, 4),
        "adjustments": adjustments,
    }
    if abstain:
        return {
            **{key: value for key, value in prediction.items() if not key.startswith("_")},
            "interventions": None,
            "governed": governed,
            "abstain_reason": "; ".join(adjustments),
        }
    if widen > 1.0:
        base: LogScaleDist = prediction["_delay_dist"]
        widened = LogScaleDist(base.loc, base.scale * widen, base.df)
        effects = prediction["_effects"]
        raw_stock = {
            name: {"p": payload["stockout"]["p"], "n": payload["stockout"]["n_prior_tasks"]}
            for name, payload in prediction["interventions"].items()
        }
        rebuilt = _package(prediction["candidate"], prediction["model_release"], compiled,
                           widened, effects, raw_stock, prediction.get("diagnostics", {}))
        prediction = {**prediction, "interventions": rebuilt["interventions"],
                      "_delay_dist": widened}
    result = dict(prediction)
    result["governed"] = governed
    return result
