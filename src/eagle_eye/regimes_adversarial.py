from __future__ import annotations

import json
import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .prior_registry import canonical_bytes, sha256_hex
from .regimes import (
    GENERATOR_RELEASE as ORIGINAL_GENERATOR_RELEASE,
    INTERVENTIONS,
    SCHEMA_VERSION,
    generate_target_case as generate_original_target_case,
    generate_world as generate_original_world,
)
from .regimes_independent import (
    GENERATOR_RELEASE as INDEPENDENT_GENERATOR_RELEASE,
    generate_independent_target,
    generate_independent_world,
)
from .stats import DeterministicRng, stable_seed

FAMILY_PANEL_RELEASE = "w-transfer-family-panel/1.0"
ORIGINAL_FRESH_FAMILY_ID = "original-fresh"
INDEPENDENT_MIXTURE_FAMILY_ID = "independent-mixture"
ANTI_PRIOR_BURST_FAMILY_ID = "anti-prior-metadata-shift"
ANTI_PRIOR_GENERATOR_RELEASE = "anti-prior-metadata-shift-generator/1.0"
FAMILY_ORDER = (
    ORIGINAL_FRESH_FAMILY_ID,
    INDEPENDENT_MIXTURE_FAMILY_ID,
    ANTI_PRIOR_BURST_FAMILY_ID,
)

_ANTI_PRIOR_CFG = {
    "port_congestion": {
        "obs_loc": math.log(8.8),
        "obs_sd": 0.18,
        "burst_prob": 0.22,
        "burst_loc": 0.46,
        "burst_sd": 0.14,
        "tail_prob": 0.02,
        "tail_scale": 0.70,
        "stockout_mid": 15.0,
        "stockout_scale": 3.3,
        "intervention_delta": {
            "wait_incumbent": 0.0,
            "expedite_shipment": -0.16,
            "activate_alternate": -0.34,
            "split_order": -0.09,
        },
    },
    "supplier_quality": {
        "obs_loc": math.log(6.4),
        "obs_sd": 0.16,
        "burst_prob": 0.18,
        "burst_loc": 0.34,
        "burst_sd": 0.12,
        "tail_prob": 0.01,
        "tail_scale": 0.55,
        "stockout_mid": 11.0,
        "stockout_scale": 2.9,
        "intervention_delta": {
            "wait_incumbent": 0.0,
            "expedite_shipment": -0.10,
            "activate_alternate": -0.27,
            "split_order": -0.05,
        },
    },
    "geopolitical": {
        "obs_loc": math.log(12.6),
        "obs_sd": 0.22,
        "burst_prob": 0.24,
        "burst_loc": 0.58,
        "burst_sd": 0.18,
        "tail_prob": 0.03,
        "tail_scale": 0.80,
        "stockout_mid": 18.0,
        "stockout_scale": 3.8,
        "intervention_delta": {
            "wait_incumbent": 0.0,
            "expedite_shipment": -0.12,
            "activate_alternate": -0.29,
            "split_order": -0.07,
        },
    },
}


def _module_sha256(path: Path) -> str:
    return sha256_hex(path.read_bytes())


def _source_commitment(*paths: Path) -> str:
    rows = [{"path": str(path.name), "sha256": _module_sha256(path)} for path in paths]
    return sha256_hex(canonical_bytes(rows))


def family_panel() -> list[dict[str, Any]]:
    here = Path(__file__).resolve()
    return [
        {
            "panel_release": FAMILY_PANEL_RELEASE,
            "family_id": ORIGINAL_FRESH_FAMILY_ID,
            "family_release": "w-transfer-original-fresh/1.0",
            "generator_release": ORIGINAL_GENERATOR_RELEASE,
            "seed_namespace": "w-transfer-original-fresh",
            "schema_release": SCHEMA_VERSION,
            "kernels": "hierarchical normal / student-t task generator",
            "dependence": "task latent theta with seasonal regime hierarchy",
            "tail": "student-t geopolitical tail only",
            "intervention": "additive log-delay shifts",
            "stockout": "beta-bernoulli task latent",
            "structural_parent": ORIGINAL_GENERATOR_RELEASE,
            "source_commitment": _source_commitment(here, Path(__file__).with_name("regimes.py")),
        },
        {
            "panel_release": FAMILY_PANEL_RELEASE,
            "family_id": INDEPENDENT_MIXTURE_FAMILY_ID,
            "family_release": "w-transfer-independent-mixture/1.0",
            "generator_release": INDEPENDENT_GENERATOR_RELEASE,
            "seed_namespace": "w-transfer-independent-mixture",
            "schema_release": SCHEMA_VERSION,
            "kernels": "gamma severity-tier mixtures with day-of-week multipliers",
            "dependence": "delay-linked stockout and mixture-tier latent severity",
            "tail": "pareto contamination",
            "intervention": "bounded multiplicative factors",
            "stockout": "delay-linked logistic hazard",
            "structural_parent": None,
            "source_commitment": _source_commitment(here, Path(__file__).with_name("regimes_independent.py")),
        },
        {
            "panel_release": FAMILY_PANEL_RELEASE,
            "family_id": ANTI_PRIOR_BURST_FAMILY_ID,
            "family_release": "w-transfer-anti-prior-metadata-shift/1.0",
            "generator_release": ANTI_PRIOR_GENERATOR_RELEASE,
            "seed_namespace": "w-transfer-anti-prior-metadata-shift",
            "schema_release": SCHEMA_VERSION,
            "kernels": "original hierarchical generator with adversarial metadata relabeling",
            "dependence": "visible supplier/lane/region labels are deterministically permuted away from latent structure",
            "tail": "inherits original family tails",
            "intervention": "inherits original additive log-delay shifts",
            "stockout": "inherits original beta-bernoulli task latent",
            "structural_parent": ORIGINAL_GENERATOR_RELEASE,
            "source_commitment": _source_commitment(here),
        },
    ]


def family_manifest(family_id: str) -> dict[str, Any]:
    return next(manifest for manifest in family_panel() if manifest["family_id"] == family_id)


def generate_family_world(
    family_id: str,
    world_seed: int,
    *,
    tasks_per_class: int = 12,
    tenant_id: str = "tenant-demo",
) -> dict[str, Any]:
    if family_id == ORIGINAL_FRESH_FAMILY_ID:
        return generate_original_world(
            world_seed,
            tasks_per_regime=tasks_per_class,
            tenants=(tenant_id,),
        )
    if family_id == INDEPENDENT_MIXTURE_FAMILY_ID:
        return generate_independent_world(
            world_seed,
            tasks_per_class=tasks_per_class,
            tenant_id=tenant_id,
        )
    if family_id == ANTI_PRIOR_BURST_FAMILY_ID:
        return _generate_anti_prior_world(
            world_seed,
            tasks_per_class=tasks_per_class,
            tenant_id=tenant_id,
        )
    raise ValueError(f"unknown family_id {family_id!r}")


def generate_family_target(
    family_id: str,
    *,
    world: dict[str, Any],
    world_seed: int,
    case_index: int,
    disruption_class: str,
    cutoff: str,
    n_target_obs: int,
    tenant_id: str = "tenant-demo",
) -> dict[str, Any]:
    if family_id == ORIGINAL_FRESH_FAMILY_ID:
        return generate_original_target_case(
            world,
            case_index=case_index,
            tenant_id=tenant_id,
            disruption_class=disruption_class,
            cutoff=cutoff,
            n_target_obs=n_target_obs,
        )
    if family_id == INDEPENDENT_MIXTURE_FAMILY_ID:
        return generate_independent_target(
            world_seed,
            case_index=case_index,
            disruption_class=disruption_class,
            cutoff=cutoff,
            n_target_obs=n_target_obs,
            tenant_id=tenant_id,
        )
    if family_id == ANTI_PRIOR_BURST_FAMILY_ID:
        return _generate_anti_prior_target(
            world_seed,
            case_index=case_index,
            disruption_class=disruption_class,
            cutoff=cutoff,
            n_target_obs=n_target_obs,
            tenant_id=tenant_id,
        )
    raise ValueError(f"unknown family_id {family_id!r}")


def _anti_prior_season(day: date) -> float:
    return 0.06 * math.sin(2.0 * math.pi * day.timetuple().tm_yday / 365.25)


_LANES = ("asia-us-west", "asia-eu", "intra-eu")
_REGIONS = ("APAC", "EMEA", "AMER")


def _rotate_label(value: str, options: tuple[str, ...], shift: int) -> str:
    if value not in options:
        return value
    return options[(options.index(value) + shift) % len(options)]


def _scramble_entity_refs(entity_refs: dict[str, Any], *, shift: int) -> dict[str, Any]:
    scrambled = dict(entity_refs)
    scrambled["supplier_id"] = f"sup-x{(shift + sum(ord(c) for c in entity_refs['supplier_id'])) % 7:03d}"
    scrambled["component_id"] = f"cmp-x{(2 * shift + sum(ord(c) for c in entity_refs['component_id'])) % 5:03d}"
    scrambled["lane"] = _rotate_label(entity_refs["lane"], _LANES, shift % len(_LANES))
    scrambled["region"] = _rotate_label(entity_refs["region"], _REGIONS, (shift + 1) % len(_REGIONS))
    return scrambled


def _anti_prior_hidden_tension(rng: DeterministicRng, cutoff_day: date, class_cfg: dict[str, Any]) -> float:
    return rng.normal(0.0, 0.55) + _anti_prior_season(cutoff_day) + class_cfg["burst_prob"] - 0.28


def _anti_prior_log_delay(
    rng: DeterministicRng,
    cutoff_day: date,
    class_cfg: dict[str, Any],
    intervention_id: str,
) -> tuple[float, bool]:
    obs_mu = class_cfg["obs_loc"] + _anti_prior_hidden_tension(rng, cutoff_day, class_cfg)
    burst = rng.uniform() < class_cfg["burst_prob"]
    if burst:
        shock = abs(rng.normal(class_cfg["burst_loc"], class_cfg["burst_sd"]))
    else:
        shock = rng.normal(0.02, class_cfg["obs_sd"] * 0.8)
    if rng.uniform() < class_cfg["tail_prob"]:
        shock += math.log(1.0 + class_cfg["tail_scale"] * rng.uniform())
    return obs_mu + shock + class_cfg["intervention_delta"][intervention_id], burst


def _stockout_probability(delay_days: float, *, burst: bool, midpoint: float, scale: float) -> float:
    p = 1.0 / (1.0 + math.exp(-(delay_days - midpoint) / scale))
    return min(0.995, p + (0.12 if burst else 0.0))


def _anti_prior_task(
    *,
    tenant_id: str,
    disruption_class: str,
    task_index: int,
    anchor: date,
    n_observations: int,
    intervention_id: str,
    world_seed: int,
) -> dict[str, Any]:
    class_cfg = _ANTI_PRIOR_CFG[disruption_class]
    rng = DeterministicRng(stable_seed("anti-prior-task", world_seed, disruption_class, tenant_id, task_index))
    tension = _anti_prior_hidden_tension(rng, anchor, class_cfg)
    obs_center = class_cfg["obs_loc"] + 0.35 * tension
    observations = []
    for index in range(n_observations):
        day = anchor + timedelta(days=2 * index)
        observations.append({
            "t": day.isoformat(),
            "kind": "shipment_delay_signal",
            "log_delay_days": round(rng.normal(obs_center + 0.03 * math.sin(index), class_cfg["obs_sd"]), 6),
        })
    outcome_day = anchor + timedelta(days=max(6, 2 * n_observations))
    log_delay, burst = _anti_prior_log_delay(rng, outcome_day, class_cfg, intervention_id)
    delay_days = max(0.35, math.exp(log_delay))
    exposure_rate = round(5500.0 + 8500.0 * rng.uniform(), 2)
    stockout = rng.uniform() < _stockout_probability(
        delay_days,
        burst=burst,
        midpoint=class_cfg["stockout_mid"],
        scale=class_cfg["stockout_scale"],
    )
    recovery = delay_days + (-math.log(max(rng.uniform(), 1e-12)) * (5.0 if burst else 3.0))
    close = anchor + timedelta(days=max(6, 2 * n_observations) + int(delay_days) + 3)
    task_id = f"pt-abh-{stable_seed('anti-prior-task-id', world_seed, disruption_class, tenant_id, task_index) % 10**10:010d}"
    return {
        "task": {
            "schema_version": SCHEMA_VERSION,
            "task_id": task_id,
            "tenant_id": tenant_id,
            "disruption_class": disruption_class,
            "as_of_start": anchor.isoformat(),
            "as_of_end": close.isoformat(),
            "entity_refs": {
                "supplier_id": f"sup-a{task_index % 5:03d}",
                "component_id": f"cmp-a{task_index % 4:03d}",
                "lane": ("asia-us-west", "asia-eu", "intra-eu")[task_index % 3],
                "region": ("APAC", "EMEA", "AMER")[task_index % 3],
                "exposure_rate_per_day_usd": exposure_rate,
            },
            "observations": observations,
            "intervention": {"id": intervention_id, "applied": True},
            "realized": {
                "final_delay_days": round(delay_days, 3),
                "log_final_delay": round(log_delay, 6),
                "stockout": stockout,
                "exposure_usd": round(exposure_rate * delay_days, 2),
                "recovery_days": round(recovery, 3),
                "intervention_success": bool(class_cfg["intervention_delta"][intervention_id] < -0.05),
            },
            "sources": [{
                "id": f"src-{task_id}",
                "kind": "authorized_synthetic_fixture",
                "generator": ANTI_PRIOR_GENERATOR_RELEASE,
            }],
            "eligibility": {"status": "closed", "quality": "complete"},
        },
        "truth": {
            "task_id": task_id,
            "generator": ANTI_PRIOR_GENERATOR_RELEASE,
            "burst": burst,
            "hidden_tension": round(tension, 6),
        },
    }


def _generate_anti_prior_world(
    world_seed: int,
    *,
    tasks_per_class: int = 12,
    tenant_id: str = "tenant-demo",
) -> dict[str, Any]:
    base_world = generate_original_world(world_seed, tasks_per_regime=tasks_per_class, tenants=(tenant_id,))
    tasks = []
    for index, task in enumerate(base_world["tasks"]):
        shift = 1 + (index % 2)
        mutated = json.loads(json.dumps(task))
        mutated["entity_refs"] = _scramble_entity_refs(task["entity_refs"], shift=shift)
        mutated["sources"][0]["generator"] = ANTI_PRIOR_GENERATOR_RELEASE
        tasks.append(mutated)
    return {
        **base_world,
        "generator_release": ANTI_PRIOR_GENERATOR_RELEASE,
        "tasks": tasks,
    }


def _generate_anti_prior_target(
    world_seed: int,
    *,
    case_index: int,
    disruption_class: str,
    cutoff: str,
    n_target_obs: int,
    tenant_id: str = "tenant-demo",
) -> dict[str, Any]:
    world = generate_original_world(world_seed, tasks_per_regime=12, tenants=(tenant_id,))
    case = generate_original_target_case(
        world,
        case_index=case_index,
        tenant_id=tenant_id,
        disruption_class=disruption_class,
        cutoff=cutoff,
        n_target_obs=n_target_obs,
    )
    shift = 2 + (case_index % 2)
    target = json.loads(json.dumps(case["target"]))
    target["entity_refs"] = _scramble_entity_refs(case["target"]["entity_refs"], shift=shift)
    return {
        "target": target,
        "truth": {**case["truth"], "generator": ANTI_PRIOR_GENERATOR_RELEASE},
    }
