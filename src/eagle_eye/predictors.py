"""Predictive candidates for the disruption engine.

Every candidate consumes the compiled prior context (prior_selector output)
and emits canonical predictive distributions per channel. All candidates share
one interface so a future neural predictor (sequential MT-ICL or Set-MT
transformer, arXiv:2606.20538) can drop in behind the same evidence chain.

Implemented candidates (algorithmic analogs of the paper's comparison set):

  climatology       pooled historical outcomes, ignores target evidence
  no_prefix         conjugate update on target observations only (no prior tasks)
  naive_pooling     pools prior + target observations as ONE task (anti-pattern)
  seq_prefix        order-sensitive recency-weighted empirical Bayes
                    (analog of the sequential multi-task prefix model)
  set_mt            permutation-invariant precision-weighted empirical Bayes
                    (analog of the Set-MT aggregator)
  oracle_hier       exact hierarchical Bayes given true variance components
                    (the amortization target; uses no hidden per-case truth)
  oracle_true       knows the hidden regime + true intervention effects
                    (upper bound; only usable on synthetic cases)

Scoring convention: delay NLL/CRPS are computed on the log-delay scale for
every candidate (monotone transform applied uniformly; proper scoring
comparisons remain valid). Day-scale quantiles are derived for operators.
"""

from __future__ import annotations

import math
from typing import Any

from .stats import norm_cdf, norm_crps, norm_logpdf, norm_ppf, t_cdf, t_crps, t_logpdf, t_ppf

INTERVENTIONS = ("wait_incumbent", "expedite_shipment", "activate_alternate", "split_order")
VAGUE = {"m0": math.log(14.0), "k0": 0.5, "a0": 1.5, "b0": 0.8}
MIN_SIGMA = 0.05
MIN_TAU = 0.02


# ---------------------------------------------------------------------------
# Distribution container (log-delay scale)
# ---------------------------------------------------------------------------

class LogScaleDist:
    """Location-scale distribution on log-delay: Normal (df=None) or Student-t."""

    def __init__(self, loc: float, scale: float, df: float | None = None):
        if scale <= 0:
            raise ValueError("scale must be positive")
        self.loc, self.scale, self.df = loc, scale, df

    def logpdf(self, y: float) -> float:
        if self.df is None:
            return norm_logpdf(y, self.loc, self.scale)
        return t_logpdf(y, self.df, self.loc, self.scale)

    def cdf(self, y: float) -> float:
        if self.df is None:
            return norm_cdf(y, self.loc, self.scale)
        return t_cdf(y, self.df, self.loc, self.scale)

    def ppf(self, p: float) -> float:
        if self.df is None:
            return norm_ppf(p, self.loc, self.scale)
        return t_ppf(p, self.df, self.loc, self.scale)

    def crps(self, y: float) -> float:
        if self.df is None:
            return norm_crps(y, self.loc, self.scale)
        return t_crps(y, self.df, self.loc, self.scale)

    def shifted(self, delta_loc: float, extra_var: float = 0.0) -> "LogScaleDist":
        return LogScaleDist(self.loc + delta_loc, math.sqrt(self.scale ** 2 + extra_var), self.df)

    def to_channel_dict(self, *, thresholds_days: list[float], interval: float,
                        day_rate: float | None = None) -> dict[str, Any]:
        quantiles = {p: math.exp(self.ppf(q)) for p, q in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))}
        lo, hi = (1 - interval) / 2, 1 - (1 - interval) / 2
        payload: dict[str, Any] = {
            "family": "normal_log" if self.df is None else "student_t_log",
            "df": self.df,
            "loc": round(self.loc, 8),
            "scale": round(self.scale, 8),
            "quantiles_days": {k: round(v, 3) for k, v in quantiles.items()},
            "interval": {
                "level": interval,
                "low_days": round(math.exp(self.ppf(lo)), 3),
                "high_days": round(math.exp(self.ppf(hi)), 3),
            },
            "p_exceeds_days": {
                str(int(t)): round(1.0 - self.cdf(math.log(t)), 6) for t in thresholds_days
            },
        }
        if day_rate is not None:
            payload["day_rate_usd"] = day_rate
        return payload


# ---------------------------------------------------------------------------
# Shared sufficient statistics
# ---------------------------------------------------------------------------

def _task_stats(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for block in blocks:
        obs = block["observations"]
        n = len(obs)
        mean = sum(obs) / n if n else None
        rows.append({
            "task_id": block["task_id"],
            "n": n,
            "mean": mean,
            "sq": sum((v - mean) ** 2 for v in obs) if n else 0.0,
            "realized": block["realized"]["log_final_delay"],
            "intervention": block["intervention_id"],
            "stockout": block["realized"]["stockout"],
        })
    return rows


def _pooled_sigma2(rows: list[dict[str, Any]]) -> tuple[float, int]:
    num = sum(r["sq"] for r in rows if r["n"] >= 2)
    den = sum(r["n"] - 1 for r in rows if r["n"] >= 2)
    if den <= 0:
        return 0.09, 0  # documented fallback prior guess (sd 0.3 on log scale)
    return max(MIN_SIGMA ** 2, num / den), den


def _weighted_moments(values: list[float], weights: list[float]) -> tuple[float, float, float]:
    wsum = sum(weights)
    mean = sum(w * v for w, v in zip(weights, values)) / wsum
    var = sum(w * (v - mean) ** 2 for w, v in zip(weights, values)) / wsum
    # Effective sample size under weighting
    ess = wsum ** 2 / sum(w * w for w in weights)
    return mean, var, ess


def _intervention_effects(rows: list[dict[str, Any]], sigma2: float) -> dict[str, dict[str, float]]:
    """Estimate per-intervention log-delay effects from realized-minus-signal gaps."""
    groups: dict[str, list[float]] = {}
    for r in rows:
        if r["n"] == 0 or r["mean"] is None:
            continue
        gap = r["realized"] - r["mean"]  # ~ N(delta_a, sigma^2 (1 + 1/n))
        groups.setdefault(r["intervention"], []).append(gap)
    effects: dict[str, dict[str, float]] = {}
    for intervention in INTERVENTIONS:
        gaps = groups.get(intervention, [])
        if not gaps:
            effects[intervention] = {"delta": 0.0, "var": 0.30 ** 2, "n": 0, "supported": False}
            continue
        n = len(gaps)
        mean = sum(gaps) / n
        # Shrink toward zero (wait_incumbent reference) with unit pseudo-count.
        shrunk = mean * n / (n + 1.0)
        gap_var = sum((g - mean) ** 2 for g in gaps) / max(1, n - 1) if n > 1 else sigma2 * 2.0
        effects[intervention] = {
            "delta": shrunk,
            "var": max(1e-6, gap_var / n),
            "n": n,
            "supported": True,
        }
    return effects


def _stockout_rates(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    # Unknown stockout outcomes (None) are EXCLUDED, never coerced to False.
    rows = [r for r in rows if r.get("stockout") is not None]
    overall_hits = sum(1 for r in rows if r["stockout"])
    overall_n = len(rows)
    base = (overall_hits + 1.0) / (overall_n + 2.0) if overall_n else 0.5
    rates: dict[str, dict[str, float]] = {}
    for intervention in INTERVENTIONS:
        group = [r for r in rows if r["intervention"] == intervention]
        hits = sum(1 for r in group if r["stockout"])
        n = len(group)
        # EB shrinkage toward the overall base rate with strength 4.
        rates[intervention] = {
            "p": (hits + 4.0 * base) / (n + 4.0),
            "n": n,
        }
    return rates


def _nig_posterior_predictive(obs: list[float], prior: dict[str, float]) -> LogScaleDist:
    """Normal-Inverse-Gamma conjugate update -> Student-t predictive."""
    m0, k0, a0, b0 = prior["m0"], prior["k0"], prior["a0"], prior["b0"]
    n = len(obs)
    if n == 0:
        scale = math.sqrt(b0 * (k0 + 1.0) / (a0 * k0))
        return LogScaleDist(m0, scale, df=2.0 * a0)
    mean = sum(obs) / n
    sq = sum((v - mean) ** 2 for v in obs)
    kn = k0 + n
    mn = (k0 * m0 + n * mean) / kn
    an = a0 + n / 2.0
    bn = b0 + 0.5 * sq + 0.5 * k0 * n * (mean - m0) ** 2 / kn
    scale = math.sqrt(bn * (kn + 1.0) / (an * kn))
    return LogScaleDist(mn, scale, df=2.0 * an)


def _recovery_stats(blocks: list[dict[str, Any]]) -> tuple[float, float]:
    # log(recovery/delay) per prior task is unavailable in compiled blocks;
    # a fixed regime-agnostic estimate is used and documented.
    return 0.35, 0.15


# ---------------------------------------------------------------------------
# Candidate implementations
# ---------------------------------------------------------------------------

def _package(name: str, release: str, compiled: dict[str, Any], delay: LogScaleDist,
             effects: dict[str, dict[str, float]], stockout: dict[str, dict[str, float]],
             diagnostics: dict[str, Any]) -> dict[str, Any]:
    query = compiled["target_block"]["query"]
    thresholds = [float(t) for t in query["delay_thresholds_days"]]
    interval = query["interval"]
    rate = compiled["target_block"]["exposure_rate_per_day_usd"]
    rec_m, rec_sd = _recovery_stats(compiled["prior_blocks"])
    per_intervention: dict[str, Any] = {}
    for intervention in INTERVENTIONS:
        effect = effects[intervention]
        dist = delay.shifted(effect["delta"], effect["var"])
        exposure = LogScaleDist(dist.loc + math.log(rate), dist.scale, dist.df)
        recovery = LogScaleDist(dist.loc + rec_m, math.sqrt(dist.scale ** 2 + rec_sd ** 2), dist.df)
        per_intervention[intervention] = {
            "delay": dist.to_channel_dict(thresholds_days=thresholds, interval=interval),
            "exposure_usd": {
                **{k: {kk: round(vv * 1.0, 2) for kk, vv in v.items()} if isinstance(v, dict) else v
                   for k, v in exposure.to_channel_dict(thresholds_days=[], interval=interval).items()
                   if k in ("interval",)},
                "family": "lognormal_shift",
                "loc": round(exposure.loc, 8),
                "scale": round(exposure.scale, 8),
                "df": exposure.df,
                "quantiles_usd": {p: round(math.exp(exposure.ppf(q)), 2)
                                  for p, q in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))},
            },
            "recovery_days": {
                "family": "lognormal_shift",
                "loc": round(recovery.loc, 8),
                "scale": round(recovery.scale, 8),
                "df": recovery.df,
                "quantiles_days": {p: round(math.exp(recovery.ppf(q)), 3)
                                   for p, q in (("p10", 0.1), ("p50", 0.5), ("p90", 0.9))},
            },
            "stockout": {"family": "bernoulli", "p": round(stockout[intervention]["p"], 6),
                          "n_prior_tasks": stockout[intervention]["n"]},
            "effect_supported": effects[intervention]["supported"] if "supported" in effects[intervention] else True,
        }
    return {
        "candidate": name,
        "model_release": release,
        "training_support": {"k_range": [0, 12], "context_range": [0, 200]},
        "K": compiled["K"],
        "context_length": compiled["context_length"],
        "prior_manifest_sha256": compiled["prior_manifest_sha256"],
        "interventions": per_intervention,
        "diagnostics": diagnostics,
        "_delay_dist": delay,          # internal handle for scoring (not serialized)
        "_effects": effects,           # internal handle for scoring (not serialized)
    }


def predict_climatology(compiled: dict[str, Any]) -> dict[str, Any]:
    rows = _task_stats(compiled["prior_blocks"])
    outcomes = [r["realized"] for r in rows]
    if not outcomes:
        dist = LogScaleDist(VAGUE["m0"], 1.0, df=3.0)
    else:
        n = len(outcomes)
        mean = sum(outcomes) / n
        var = sum((v - mean) ** 2 for v in outcomes) / max(1, n - 1)
        dist = LogScaleDist(mean, math.sqrt(max(MIN_SIGMA ** 2, var) * (1.0 + 1.0 / n)), df=max(3.0, n - 1.0))
    effects = {i: {"delta": 0.0, "var": 0.0, "n": 0, "supported": False} for i in INTERVENTIONS}
    return _package("climatology", "climatology/1.0", compiled, dist, effects,
                    _stockout_rates(rows), {"note": "pooled historical outcomes; target evidence ignored"})


def predict_no_prefix(compiled: dict[str, Any]) -> dict[str, Any]:
    target_obs = compiled["target_block"]["observations"]
    dist = _nig_posterior_predictive(target_obs, VAGUE)
    effects = {i: {"delta": 0.0, "var": 0.35 ** 2, "n": 0, "supported": False} for i in INTERVENTIONS}
    stockout = {i: {"p": 0.5, "n": 0} for i in INTERVENTIONS}
    return _package("no_prefix", "no-prefix-conjugate/1.0", compiled, dist, effects, stockout,
                    {"note": "target-only conjugate update; interventions indistinguishable"})


def predict_naive_pooling(compiled: dict[str, Any]) -> dict[str, Any]:
    rows = _task_stats(compiled["prior_blocks"])
    pooled: list[float] = []
    for block in compiled["prior_blocks"]:
        pooled.extend(block["observations"])
        pooled.append(block["realized"]["log_final_delay"])
    pooled.extend(compiled["target_block"]["observations"])
    dist = _nig_posterior_predictive(pooled, VAGUE)
    sigma2, _ = _pooled_sigma2(rows)
    effects = _intervention_effects(rows, sigma2)
    return _package("naive_pooling", "naive-pooling/1.0", compiled, dist, effects,
                    _stockout_rates(rows),
                    {"note": "prior and target observations pooled as one latent task (anti-pattern)"})


def _two_stage_predictive(m_hat: float, v_m: float, tau2: float, sigma2: float,
                          target_obs: list[float], df: float) -> LogScaleDist:
    """Hierarchical two-stage update: hyper posterior -> target latent -> predictive."""
    prior_var = v_m + tau2
    n = len(target_obs)
    if n:
        ybar = sum(target_obs) / n
        like_var = sigma2 / n
        post_var = 1.0 / (1.0 / prior_var + 1.0 / like_var)
        post_mean = post_var * (m_hat / prior_var + ybar / like_var)
    else:
        post_mean, post_var = m_hat, prior_var
    return LogScaleDist(post_mean, math.sqrt(post_var + sigma2), df=df)


def predict_seq_prefix(compiled: dict[str, Any], *, decay: float = 0.8) -> dict[str, Any]:
    """Order-sensitive recency-weighted empirical Bayes (sequential analog).

    Task weights decay geometrically with distance from the END of the prior
    prefix, so permuting the prior blocks changes the prediction — the same
    structural property (and hazard) as the sequential MT-ICL transformer.
    """
    rows = _task_stats(compiled["prior_blocks"])
    usable = [r for r in rows if r["n"] > 0]
    target_obs = compiled["target_block"]["observations"]
    if not usable:
        return {**predict_no_prefix(compiled), "candidate": "seq_prefix",
                "model_release": "seq-prefix-eb/1.0"}
    sigma2, _ = _pooled_sigma2(usable)
    weights = [decay ** (len(usable) - 1 - idx) for idx in range(len(usable))]
    means = [r["mean"] for r in usable]
    m_hat, between_var, ess = _weighted_moments(means, weights)
    mean_inv_n = sum(w / r["n"] for w, r in zip(weights, usable)) / sum(weights)
    tau2 = max(MIN_TAU ** 2, between_var - sigma2 * mean_inv_n)
    v_m = (tau2 + sigma2 * mean_inv_n) / max(1.0, ess)
    dist = _two_stage_predictive(m_hat, v_m, tau2, sigma2, target_obs, df=max(3.0, ess - 1.0))
    effects = _intervention_effects(usable, sigma2)
    return _package("seq_prefix", "seq-prefix-eb/1.0", compiled, dist, effects,
                    _stockout_rates(rows),
                    {"m_hat": round(m_hat, 6), "tau2": round(tau2, 6), "sigma2": round(sigma2, 6),
                     "ess": round(ess, 3), "decay": decay,
                     "note": "recency-weighted; order-sensitive by construction"})


def predict_set_mt(compiled: dict[str, Any]) -> dict[str, Any]:
    """Permutation-invariant precision-weighted empirical Bayes (Set-MT analog)."""
    rows = _task_stats(compiled["prior_blocks"])
    usable = sorted((r for r in rows if r["n"] > 0), key=lambda r: r["task_id"])
    target_obs = compiled["target_block"]["observations"]
    if not usable:
        return {**predict_no_prefix(compiled), "candidate": "set_mt",
                "model_release": "set-mt-eb/1.0"}
    sigma2, _ = _pooled_sigma2(usable)
    means = [r["mean"] for r in usable]
    k = len(means)
    grand = sum(means) / k
    between = sum((m - grand) ** 2 for m in means) / max(1, k - 1)
    mean_inv_n = sum(1.0 / r["n"] for r in usable) / k
    tau2 = max(MIN_TAU ** 2, between - sigma2 * mean_inv_n)
    weights = [1.0 / (tau2 + sigma2 / r["n"]) for r in usable]
    m_hat = sum(w * m for w, m in zip(weights, means)) / sum(weights)
    v_m = 1.0 / sum(weights)
    dist = _two_stage_predictive(m_hat, v_m, tau2, sigma2, target_obs, df=max(3.0, k - 1.0))
    effects = _intervention_effects(usable, sigma2)
    return _package("set_mt", "set-mt-eb/1.0", compiled, dist, effects,
                    _stockout_rates(rows),
                    {"m_hat": round(m_hat, 6), "tau2": round(tau2, 6), "sigma2": round(sigma2, 6),
                     "K_used": k, "note": "permutation-invariant set aggregation"})


def predict_oracle_hier(compiled: dict[str, Any], truth_hyper: dict[str, Any]) -> dict[str, Any]:
    """Exact hierarchical Bayes given true variance components (tau, sigma).

    Infers the regime level m from the prior prefix exactly (flat hyperprior),
    then performs the exact two-stage update. This is the amortization target
    the paper's transformer approximates.
    """
    tau2 = truth_hyper["tau"] ** 2
    sigma2 = truth_hyper["sigma"] ** 2
    rows = [r for r in _task_stats(compiled["prior_blocks"]) if r["n"] > 0]
    target_obs = compiled["target_block"]["observations"]
    if rows:
        weights = [1.0 / (tau2 + sigma2 / r["n"]) for r in rows]
        m_hat = sum(w * r["mean"] for w, r in zip(weights, rows)) / sum(weights)
        v_m = 1.0 / sum(weights)
    else:
        m_hat, v_m = VAGUE["m0"], 4.0
    dist = _two_stage_predictive(m_hat, v_m, tau2, sigma2, target_obs, df=None)  # exact normal
    effects = _intervention_effects(rows, sigma2)
    return _package("oracle_hier", "oracle-hier-exact/1.0", compiled, dist, effects,
                    _stockout_rates(_task_stats(compiled["prior_blocks"])),
                    {"m_hat": round(m_hat, 6), "v_m": round(v_m, 8),
                     "note": "exact hierarchical posterior with true variance components"})


def predict_oracle_true(compiled: dict[str, Any], case_truth: dict[str, Any]) -> dict[str, Any]:
    """Upper bound: knows the hidden regime mean, variances, seasonality, and
    true intervention effect distributions. Only valid on synthetic cases."""
    hyper = case_truth["hyper"]
    tau2, sigma2 = hyper["tau"] ** 2, hyper["sigma"] ** 2
    target_obs = compiled["target_block"]["observations"]
    seasonal = 0.0  # folded into theta draw; regime m is the anchor
    dist = _two_stage_predictive(hyper["m"] + seasonal, 0.0, tau2, sigma2, target_obs, df=None)
    effects = {
        name: {"delta": cfg["d_mean"], "var": cfg["d_sd"] ** 2, "n": 999, "supported": True}
        for name, cfg in hyper["interventions"].items()
    }
    stock = hyper["stockout"]
    stockout = {
        name: {"p": stock["mean"] * (0.65 if name != "wait_incumbent" else 1.0), "n": 999}
        for name in INTERVENTIONS
    }
    return _package("oracle_true", "oracle-true-regime/1.0", compiled, dist, effects, stockout,
                    {"note": "knows hidden regime; upper bound only"})


CANDIDATES = {
    "climatology": predict_climatology,
    "no_prefix": predict_no_prefix,
    "naive_pooling": predict_naive_pooling,
    "seq_prefix": predict_seq_prefix,
    "set_mt": predict_set_mt,
}
