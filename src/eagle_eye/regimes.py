"""Synthetic supply-chain disruption regime generator with hidden ground truth.

Generative hierarchy (mirrors Multi-Task Bayesian ICL, arXiv:2606.20538):

    regime lambda  ~ configured hyperparameters          (hidden)
    task theta_i   ~ Normal(m_regime + seasonal, tau^2)  (hidden, log-delay scale)
    obs y_ij       ~ Normal(theta_i, sigma^2)            (observed, log of days)
    outcome y_new  ~ Normal(theta_i + delta_interv, sigma^2)  (realized later)

All sampling is driven by DeterministicRng(stable_seed(...)) so every world,
task, and case is exactly reproducible from its release string and seed.

Ground truth (regime hyperparameters and per-task latents) is returned in a
SEPARATE structure from the registry-facing tasks so that predictors can never
read it; only the oracle comparisons in the evaluation court may.

Fixed channels:
    delay_days      = exp(y_new)
    exposure_usd    = exposure_rate_per_day * delay_days       (rate is known metadata)
    recovery_days   = delay_days * exp(rho),  rho ~ Normal(r_m, r_sd)  (regime level)
    stockout        ~ Bernoulli(p_i),  p_i ~ Beta(mean*conc, (1-mean)*conc)
    intervention a  shifts y_new by delta_a,  delta_a ~ Normal(d_mean_a, d_sd_a)
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from .stats import DeterministicRng, stable_seed

SCHEMA_VERSION = "prior-task/1.0"
GENERATOR_RELEASE = "synthetic-regime-generator/1.0"

INTERVENTIONS = ("wait_incumbent", "expedite_shipment", "activate_alternate", "split_order")


def _iso(day: date) -> str:
    return day.isoformat()


def _doy(day: date) -> int:
    return day.timetuple().tm_yday


def default_world_config() -> dict[str, Any]:
    """Two-tenant, multi-regime world used by fixtures and the court suites."""
    return {
        "generator_release": GENERATOR_RELEASE,
        "start": "2024-01-01",
        "regimes": [
            {
                "regime_id": "regime-port-congestion-a",
                "disruption_class": "port_congestion",
                "window": {"start": "2024-01-01", "end": "2025-06-30"},
                "hyper": {
                    "m": math.log(12.0), "tau": 0.25, "sigma": 0.30,
                    "heavy_tail_df": None,
                    "seasonality": {"amplitude": 0.10, "peak_doy": 46},
                    "stockout": {"mean": 0.28, "concentration": 18.0},
                    "recovery": {"log_mult_mean": 0.35, "log_mult_sd": 0.10},
                    "interventions": {
                        "wait_incumbent": {"d_mean": 0.0, "d_sd": 0.02},
                        "expedite_shipment": {"d_mean": -0.45, "d_sd": 0.10},
                        "activate_alternate": {"d_mean": -0.30, "d_sd": 0.22},
                        "split_order": {"d_mean": -0.18, "d_sd": 0.08},
                    },
                },
            },
            {
                "regime_id": "regime-port-congestion-shifted",
                "disruption_class": "port_congestion",
                "window": {"start": "2025-07-01", "end": "2026-12-31"},
                "hyper": {
                    "m": math.log(21.0), "tau": 0.32, "sigma": 0.34,
                    "heavy_tail_df": None,
                    "seasonality": {"amplitude": 0.10, "peak_doy": 46},
                    "stockout": {"mean": 0.44, "concentration": 14.0},
                    "recovery": {"log_mult_mean": 0.45, "log_mult_sd": 0.12},
                    "interventions": {
                        "wait_incumbent": {"d_mean": 0.0, "d_sd": 0.02},
                        "expedite_shipment": {"d_mean": -0.28, "d_sd": 0.12},
                        "activate_alternate": {"d_mean": -0.42, "d_sd": 0.18},
                        "split_order": {"d_mean": -0.22, "d_sd": 0.09},
                    },
                },
            },
            {
                "regime_id": "regime-supplier-quality",
                "disruption_class": "supplier_quality",
                "window": {"start": "2024-01-01", "end": "2026-12-31"},
                "hyper": {
                    "m": math.log(7.0), "tau": 0.35, "sigma": 0.28,
                    "heavy_tail_df": None,
                    "seasonality": {"amplitude": 0.0, "peak_doy": 1},
                    "stockout": {"mean": 0.15, "concentration": 22.0},
                    "recovery": {"log_mult_mean": 0.25, "log_mult_sd": 0.08},
                    "interventions": {
                        "wait_incumbent": {"d_mean": 0.0, "d_sd": 0.02},
                        "expedite_shipment": {"d_mean": -0.20, "d_sd": 0.09},
                        "activate_alternate": {"d_mean": -0.35, "d_sd": 0.15},
                        "split_order": {"d_mean": -0.15, "d_sd": 0.07},
                    },
                },
            },
            {
                "regime_id": "regime-heavy-tail-geo",
                "disruption_class": "geopolitical",
                "window": {"start": "2024-01-01", "end": "2026-12-31"},
                "hyper": {
                    "m": math.log(15.0), "tau": 0.40, "sigma": 0.45,
                    "heavy_tail_df": 3.0,
                    "seasonality": {"amplitude": 0.0, "peak_doy": 1},
                    "stockout": {"mean": 0.38, "concentration": 8.0},
                    "recovery": {"log_mult_mean": 0.55, "log_mult_sd": 0.20},
                    "interventions": {
                        "wait_incumbent": {"d_mean": 0.0, "d_sd": 0.03},
                        "expedite_shipment": {"d_mean": -0.25, "d_sd": 0.18},
                        "activate_alternate": {"d_mean": -0.30, "d_sd": 0.30},
                        "split_order": {"d_mean": -0.20, "d_sd": 0.15},
                    },
                },
            },
        ],
    }


def _seasonal(hyper: dict[str, Any], day: date) -> float:
    season = hyper["seasonality"]
    if not season["amplitude"]:
        return 0.0
    angle = 2.0 * math.pi * (_doy(day) - season["peak_doy"]) / 365.25
    return season["amplitude"] * math.cos(angle)


def _sample_task_latents(hyper: dict[str, Any], anchor: date, rng: DeterministicRng) -> dict[str, Any]:
    theta = rng.normal(hyper["m"] + _seasonal(hyper, anchor), hyper["tau"])
    stock = hyper["stockout"]
    p_stockout = rng.beta(stock["mean"] * stock["concentration"], (1.0 - stock["mean"]) * stock["concentration"])
    return {"theta": theta, "p_stockout": p_stockout}


def _sample_obs(hyper: dict[str, Any], theta: float, rng: DeterministicRng) -> float:
    df = hyper.get("heavy_tail_df")
    if df:
        return rng.student_t(df, theta, hyper["sigma"])
    return rng.normal(theta, hyper["sigma"])


_MAX_SYNTHETIC_DELAY_DAYS = 3650.0
_MAX_SYNTHETIC_RECOVERY_DAYS = 36500.0


def _bounded_days_from_log(value: float, cap: float) -> float:
    """Convert a synthetic log-duration without allowing pathological tails
    to overflow ``exp``/``timedelta`` or emit non-finite receipt values.

    The generator intentionally includes a Student-t regime, whose support is
    unbounded. Capping only the physically meaningless extreme tail keeps every
    generated task representable while leaving ordinary samples unchanged.
    """
    return math.exp(min(value, math.log(cap)))


def generate_task(
    *,
    regime: dict[str, Any],
    tenant_id: str,
    task_index: int,
    anchor: date,
    n_observations: int,
    intervention_id: str,
    world_seed: int,
    missing_rate: float = 0.0,
) -> dict[str, Any]:
    """Generate one closed historical disruption task plus its hidden truth."""
    hyper = regime["hyper"]
    rng = DeterministicRng(stable_seed("task", world_seed, regime["regime_id"], tenant_id, task_index))
    latents = _sample_task_latents(hyper, anchor, rng)
    theta = latents["theta"]

    observations = []
    kept = 0
    for j in range(n_observations):
        value = _sample_obs(hyper, theta, rng)
        masked = rng.uniform() < missing_rate
        if masked:
            continue
        kept += 1
        observations.append({
            "t": _iso(anchor + timedelta(days=2 * j)),
            "kind": "shipment_delay_signal",
            "log_delay_days": round(value, 6),
        })

    effect_cfg = hyper["interventions"][intervention_id]
    delta = rng.normal(effect_cfg["d_mean"], effect_cfg["d_sd"])
    y_new = _sample_obs(hyper, theta + delta, rng)
    delay_days = _bounded_days_from_log(y_new, _MAX_SYNTHETIC_DELAY_DAYS)
    stockout = rng.bernoulli(latents["p_stockout"] * (0.65 if intervention_id != "wait_incumbent" else 1.0))
    rec = hyper["recovery"]
    rho = rng.normal(rec["log_mult_mean"], rec["log_mult_sd"])
    exposure_rate = round(math.exp(rng.normal(math.log(9000.0), 0.35)), 2)
    close = anchor + timedelta(days=max(6, 2 * n_observations) + int(delay_days) + 3)

    task_id = f"pt-{stable_seed('task-id', world_seed, regime['regime_id'], tenant_id, task_index) % 10**10:010d}"
    task = {
        "schema_version": SCHEMA_VERSION,
        "task_id": task_id,
        "tenant_id": tenant_id,
        "disruption_class": regime["disruption_class"],
        "as_of_start": _iso(anchor),
        "as_of_end": _iso(close),
        "entity_refs": {
            "supplier_id": f"sup-{task_index % 7:03d}",
            "component_id": f"cmp-{task_index % 5:03d}",
            "lane": ("asia-us-west", "asia-eu", "intra-eu")[task_index % 3],
            "region": ("APAC", "EMEA", "AMER")[task_index % 3],
            "exposure_rate_per_day_usd": exposure_rate,
        },
        "observations": observations,
        "intervention": {"id": intervention_id, "applied": True},
        "realized": {
            "final_delay_days": round(delay_days, 3),
            "log_final_delay": round(y_new, 6),
            "stockout": stockout,
            "exposure_usd": round(exposure_rate * delay_days, 2),
            "recovery_days": round(min(
                delay_days * _bounded_days_from_log(
                    rho, _MAX_SYNTHETIC_RECOVERY_DAYS),
                _MAX_SYNTHETIC_RECOVERY_DAYS), 3),
            "intervention_success": bool(delta < effect_cfg["d_mean"] + effect_cfg["d_sd"]),
        },
        "sources": [{"id": f"src-{task_id}", "kind": "authorized_synthetic_fixture", "generator": GENERATOR_RELEASE}],
        "eligibility": {"status": "closed", "quality": "complete" if kept == n_observations else "partial"},
    }
    truth = {
        "task_id": task_id,
        "regime_id": regime["regime_id"],
        "theta": theta,
        "p_stockout": latents["p_stockout"],
        "delta_applied": delta,
        "seasonal": _seasonal(hyper, anchor),
    }
    return {"task": task, "truth": truth}


def generate_world(world_seed: int, config: dict[str, Any] | None = None,
                   *, tasks_per_regime: int = 24, tenants: tuple[str, ...] = ("tenant-demo", "tenant-other"),
                   missing_rate: float = 0.05) -> dict[str, Any]:
    """Generate the full historical world: registry-facing tasks + hidden truth."""
    config = config or default_world_config()
    tasks: list[dict[str, Any]] = []
    truths: dict[str, Any] = {}
    for regime in config["regimes"]:
        window_start = date.fromisoformat(regime["window"]["start"])
        window_end = date.fromisoformat(regime["window"]["end"])
        span = max(1, (window_end - window_start).days - 60)
        for tenant_index, tenant_id in enumerate(tenants):
            for i in range(tasks_per_regime):
                rng = DeterministicRng(stable_seed("anchor", world_seed, regime["regime_id"], tenant_id, i))
                anchor = window_start + timedelta(days=int(rng.uniform(0.0, span)))
                n_obs = 3 + rng.choice_index(6)
                intervention = INTERVENTIONS[rng.choice_index(len(INTERVENTIONS))]
                result = generate_task(
                    regime=regime, tenant_id=tenant_id, task_index=i + 1000 * tenant_index,
                    anchor=anchor, n_observations=n_obs, intervention_id=intervention,
                    world_seed=world_seed, missing_rate=missing_rate,
                )
                tasks.append(result["task"])
                truths[result["truth"]["task_id"]] = result["truth"]
    tasks.sort(key=lambda t: (t["as_of_end"], t["task_id"]))
    return {
        "generator_release": config["generator_release"],
        "world_seed": world_seed,
        "config": config,
        "tasks": tasks,
        "truth": {"regimes": {r["regime_id"]: r for r in config["regimes"]}, "tasks": truths},
    }


def generate_target_case(
    world: dict[str, Any],
    *,
    case_index: int,
    tenant_id: str,
    disruption_class: str,
    cutoff: str,
    n_target_obs: int,
    intervention_id: str = "wait_incumbent",
) -> dict[str, Any]:
    """Generate a live target disruption at `cutoff` plus its hidden truth.

    The target's realized outcome is generated (so the court can score) but is
    stored ONLY in the truth block, never in the target context handed to
    predictors.
    """
    cutoff_day = date.fromisoformat(cutoff)
    regime = next(
        (
            r for r in world["config"]["regimes"]
            if r["disruption_class"] == disruption_class
            and r["window"]["start"] <= cutoff <= r["window"]["end"]
        ),
        None,
    )
    if regime is None:
        raise ValueError(f"no regime covers class={disruption_class} at cutoff={cutoff}")
    hyper = regime["hyper"]
    rng = DeterministicRng(stable_seed("target", world["world_seed"], case_index, tenant_id, disruption_class, cutoff))
    latents = _sample_task_latents(hyper, cutoff_day, rng)
    theta = latents["theta"]
    observations = []
    for j in range(n_target_obs):
        observations.append({
            "t": _iso(cutoff_day - timedelta(days=2 * (n_target_obs - j))),
            "kind": "shipment_delay_signal",
            "log_delay_days": round(_sample_obs(hyper, theta, rng), 6),
        })
    exposure_rate = round(math.exp(rng.normal(math.log(9000.0), 0.35)), 2)

    outcomes: dict[str, Any] = {}
    for candidate_intervention in INTERVENTIONS:
        effect_cfg = hyper["interventions"][candidate_intervention]
        delta = rng.normal(effect_cfg["d_mean"], effect_cfg["d_sd"])
        y_new = _sample_obs(hyper, theta + delta, rng)
        delay = _bounded_days_from_log(y_new, _MAX_SYNTHETIC_DELAY_DAYS)
        rec = hyper["recovery"]
        rho = rng.normal(rec["log_mult_mean"], rec["log_mult_sd"])
        stockout = rng.bernoulli(latents["p_stockout"] * (0.65 if candidate_intervention != "wait_incumbent" else 1.0))
        outcomes[candidate_intervention] = {
            "log_final_delay": y_new,
            "final_delay_days": delay,
            "stockout": stockout,
            "exposure_usd": exposure_rate * delay,
            "recovery_days": min(
                delay * _bounded_days_from_log(
                    rho, _MAX_SYNTHETIC_RECOVERY_DAYS),
                _MAX_SYNTHETIC_RECOVERY_DAYS),
        }

    case_id = f"case-{stable_seed('case-id', world['world_seed'], case_index, tenant_id, cutoff) % 10**10:010d}"
    target = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id,
        "tenant_id": tenant_id,
        "disruption_class": disruption_class,
        "as_of_cutoff": cutoff,
        "entity_refs": {
            "supplier_id": "sup-live",
            "component_id": "cmp-live",
            "lane": "asia-us-west",
            "region": "APAC",
            "exposure_rate_per_day_usd": exposure_rate,
        },
        "observations": observations,
        "intervention": {"id": intervention_id, "applied": False},
        "query": {
            "channels": ["delay", "stockout", "exposure", "recovery"],
            "delay_thresholds_days": [14, 21],
            "interval": 0.8,
        },
    }
    truth = {
        "case_id": case_id,
        "regime_id": regime["regime_id"],
        "theta": theta,
        "p_stockout": latents["p_stockout"],
        "outcomes": outcomes,
        "hyper": hyper,
    }
    return {"target": target, "truth": truth}
