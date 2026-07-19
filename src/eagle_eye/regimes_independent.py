"""Structurally INDEPENDENT synthetic generator (V4 blocker 5).

This is not a parameter variation of `regimes.py` — it is a different
generative process, sharing only the prior-task SCHEMA:

  regimes.py (original)                 regimes_independent.py (this file)
  ---------------------                 ----------------------------------
  log-delay ~ Normal/Student-t          delay-days ~ Gamma(k, theta) mixture
  task theta ~ Normal(m + season, tau)  task severity ~ categorical TIER
  annual cosine seasonality             day-of-week multiplier
  additive log intervention effects     multiplicative Beta-bounded factors
  stockout ~ Beta-Bernoulli (indep.)    stockout ~ logistic(realized delay)
  recovery = delay * lognormal mult     recovery = delay + Exponential days
  no contamination                      5% Pareto heavy-tail contamination

Candidates trained/tuned against the original family therefore face an alien
process here. Evidence class for anything measured on this generator:
SYNTHETIC INDEPENDENT-GENERATOR TRANSFER — structurally distinct synthetic
family; NOT live-data evidence and NOT "general generator robustness".
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from .stats import DeterministicRng, stable_seed

SCHEMA_VERSION = "prior-task/1.0"
GENERATOR_RELEASE = "independent-mixture-generator/1.0"
INTERVENTIONS = ("wait_incumbent", "expedite_shipment", "activate_alternate", "split_order")

# severity tiers: (probability, gamma shape k, gamma scale theta in days)
TIERS = {
    "port_congestion": [(0.5, 6.0, 1.8), (0.35, 8.0, 3.0), (0.15, 5.0, 7.0)],
    "supplier_quality": [(0.6, 4.0, 1.5), (0.3, 6.0, 2.2), (0.1, 4.0, 5.0)],
    "geopolitical": [(0.45, 3.0, 3.5), (0.35, 5.0, 4.5), (0.2, 3.0, 9.0)],
}
# multiplicative intervention factor ~ 1 - Beta(a, b) * cap  (bounded in (1-cap, 1])
INTERVENTION_FACTORS = {
    "wait_incumbent": (0.0, None, None),
    "expedite_shipment": (0.45, 2.0, 3.0),
    "activate_alternate": (0.40, 1.6, 2.4),
    "split_order": (0.25, 2.2, 4.0),
}
DOW_MULT = [1.00, 0.97, 0.95, 0.98, 1.04, 1.12, 1.08]  # Mon..Sun
PARETO_CONTAMINATION = 0.05
PARETO_ALPHA = 1.6


def _tier(rng: DeterministicRng, disruption_class: str) -> tuple[float, float]:
    u = rng.uniform()
    acc = 0.0
    for p, k, theta in TIERS[disruption_class]:
        acc += p
        if u <= acc:
            return k, theta
    return TIERS[disruption_class][-1][1:]


def _gamma(rng: DeterministicRng, shape: float, scale: float) -> float:
    """Marsaglia-Tsang via deterministic rng (shape >= 1 after boost)."""
    boost = 1.0
    if shape < 1.0:
        boost = rng.uniform() ** (1.0 / shape)
        shape += 1.0
    d = shape - 1.0 / 3.0
    c = 1.0 / math.sqrt(9.0 * d)
    while True:
        x = rng.normal(0.0, 1.0)
        v = (1.0 + c * x) ** 3
        if v <= 0:
            continue
        u = rng.uniform()
        if u < 1.0 - 0.0331 * x ** 4 or math.log(u) < 0.5 * x * x + d * (1.0 - v + math.log(v)):
            return d * v * scale * boost


def _beta(rng: DeterministicRng, a: float, b: float) -> float:
    x = _gamma(rng, a, 1.0)
    y = _gamma(rng, b, 1.0)
    return x / (x + y)


def _draw_delay_days(rng: DeterministicRng, k: float, theta: float, day: date) -> float:
    base = _gamma(rng, k, theta) * DOW_MULT[day.weekday()]
    if rng.uniform() < PARETO_CONTAMINATION:
        base *= (1.0 - rng.uniform()) ** (-1.0 / PARETO_ALPHA)  # Pareto shock
    return max(0.25, base)


def _intervention_factor(rng: DeterministicRng, intervention: str) -> float:
    cap, a, b = INTERVENTION_FACTORS[intervention]
    if not cap:
        return 1.0
    return 1.0 - cap * _beta(rng, a, b)


def _stockout(rng: DeterministicRng, delay_days: float) -> bool:
    p = 1.0 / (1.0 + math.exp(-(delay_days - 14.0) / 4.0))  # delay-DEPENDENT
    return rng.uniform() < p


def generate_independent_task(*, tenant_id: str, disruption_class: str, task_index: int,
                              anchor: date, n_observations: int, intervention_id: str,
                              world_seed: int) -> dict[str, Any]:
    rng = DeterministicRng(stable_seed("ind-task", world_seed, disruption_class, tenant_id, task_index))
    k, theta = _tier(rng, disruption_class)
    observations = []
    for j in range(n_observations):
        day = anchor + timedelta(days=2 * j)
        observations.append({
            "t": day.isoformat(), "kind": "shipment_delay_signal",
            "log_delay_days": round(math.log(_draw_delay_days(rng, k, theta, day)), 6),
        })
    factor = _intervention_factor(rng, intervention_id)
    outcome_day = anchor + timedelta(days=max(6, 2 * n_observations))
    delay = _draw_delay_days(rng, k, theta, outcome_day) * factor
    stockout = _stockout(rng, delay)
    # recovery = delay + Exponential(mean 4 days) via inverse-CDF draw
    recovery = delay - math.log(max(rng.uniform(), 1e-12)) * 4.0
    exposure_rate = round(6000.0 + 9000.0 * rng.uniform(), 2)
    close = anchor + timedelta(days=max(6, 2 * n_observations) + int(delay) + 3)
    task_id = f"pt-ind-{stable_seed('ind-task-id', world_seed, disruption_class, tenant_id, task_index) % 10**10:010d}"
    return {
        "task": {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id, "tenant_id": tenant_id,
            "disruption_class": disruption_class,
            "as_of_start": anchor.isoformat(), "as_of_end": close.isoformat(),
            "entity_refs": {"supplier_id": f"sup-i{task_index % 5:03d}",
                             "component_id": f"cmp-i{task_index % 4:03d}",
                             "lane": ("asia-us-west", "asia-eu", "intra-eu")[task_index % 3],
                             "region": ("APAC", "EMEA", "AMER")[task_index % 3],
                             "exposure_rate_per_day_usd": exposure_rate},
            "observations": observations,
            "intervention": {"id": intervention_id, "applied": True},
            "realized": {"final_delay_days": round(delay, 3),
                          "log_final_delay": round(math.log(delay), 6),
                          "stockout": stockout,
                          "exposure_usd": round(exposure_rate * delay, 2),
                          "recovery_days": round(recovery, 3),
                          "intervention_success": bool(factor < 0.95)},
            "sources": [{"id": f"src-{task_id}", "kind": "authorized_synthetic_fixture",
                          "generator": GENERATOR_RELEASE}],
            "eligibility": {"status": "closed", "quality": "complete"},
        },
        "truth": {"task_id": task_id, "tier": [k, theta], "generator": GENERATOR_RELEASE},
    }


def generate_independent_world(world_seed: int, *, tasks_per_class: int = 12,
                               tenant_id: str = "tenant-demo") -> dict[str, Any]:
    start = date(2024, 1, 15)
    tasks = []
    for disruption_class in sorted(TIERS):
        for i in range(tasks_per_class):
            rng = DeterministicRng(stable_seed("ind-anchor", world_seed, disruption_class, i))
            anchor = start + timedelta(days=int(rng.uniform(0.0, 420.0)))
            n_obs = 3 + rng.choice_index(5)
            intervention = INTERVENTIONS[rng.choice_index(len(INTERVENTIONS))]
            tasks.append(generate_independent_task(
                tenant_id=tenant_id, disruption_class=disruption_class, task_index=i,
                anchor=anchor, n_observations=n_obs, intervention_id=intervention,
                world_seed=world_seed))
    tasks.sort(key=lambda t: (t["task"]["as_of_end"], t["task"]["task_id"]))
    return {"generator_release": GENERATOR_RELEASE, "world_seed": world_seed,
            "tasks": [t["task"] for t in tasks]}


def generate_independent_target(world_seed: int, *, case_index: int,
                                disruption_class: str, cutoff: str,
                                n_target_obs: int,
                                tenant_id: str = "tenant-demo") -> dict[str, Any]:
    cutoff_day = date.fromisoformat(cutoff)
    rng = DeterministicRng(stable_seed("ind-target", world_seed, case_index, disruption_class, cutoff))
    k, theta = _tier(rng, disruption_class)
    observations = []
    for j in range(n_target_obs):
        day = cutoff_day - timedelta(days=2 * (n_target_obs - j))
        observations.append({
            "t": day.isoformat(), "kind": "shipment_delay_signal",
            "log_delay_days": round(math.log(_draw_delay_days(rng, k, theta, day)), 6),
        })
    exposure_rate = round(6000.0 + 9000.0 * rng.uniform(), 2)
    outcomes = {}
    for intervention in INTERVENTIONS:
        factor = _intervention_factor(rng, intervention)
        delay = _draw_delay_days(rng, k, theta, cutoff_day + timedelta(days=3)) * factor
        outcomes[intervention] = {
            "log_final_delay": math.log(delay),
            "final_delay_days": delay,
            "stockout": _stockout(rng, delay),
            "exposure_usd": exposure_rate * delay,
            "recovery_days": delay - math.log(max(rng.uniform(), 1e-12)) * 4.0,
        }
    case_id = f"case-ind-{stable_seed('ind-case-id', world_seed, case_index, cutoff) % 10**10:010d}"
    target = {
        "schema_version": SCHEMA_VERSION,
        "case_id": case_id, "tenant_id": tenant_id,
        "disruption_class": disruption_class, "as_of_cutoff": cutoff,
        "entity_refs": {"supplier_id": "sup-live", "component_id": "cmp-live",
                         "lane": "asia-us-west", "region": "APAC",
                         "exposure_rate_per_day_usd": exposure_rate},
        "observations": observations,
        "intervention": {"id": "wait_incumbent", "applied": False},
        "query": {"channels": ["delay", "stockout", "exposure", "recovery"],
                   "delay_thresholds_days": [14, 21], "interval": 0.8},
    }
    return {"target": target, "truth": {"case_id": case_id, "outcomes": outcomes,
                                         "generator": GENERATOR_RELEASE}}
