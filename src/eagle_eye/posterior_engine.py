"""Posterior intelligence engine: registry -> selector -> compiler -> governed
candidate -> intervention comparison -> evidence commitments.

Attaches a `posterior_intelligence` block to an Eagle Eye run. Every field a
verifier must trust is committed with a hash that BOTH the Python and Node
verifiers can recompute from run.json alone.

Cross-runtime hash discipline (brittle point B6): any structure whose hash is
recomputed after JSON round-trips is either float-free (selector receipts,
calibration receipts) or hashed through `quantize_micro`, which maps every
non-integer number to round(x * 1e6) using half-up rounding — implemented
identically in verifier/verify.mjs.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path
import json
from typing import Any

from .governor import govern
from .predictors import CANDIDATES, predict_set_mt
from .prior_registry import build_registry, canonical_bytes, sha256_hex
from .prior_selector import compile_prior_context, select_prior_tasks
from .regimes import GENERATOR_RELEASE, SCHEMA_VERSION, generate_world
from .stats import stable_seed, DeterministicRng

ENGINE_RELEASE = "posterior-intelligence-engine/1.0"
POSTERIOR_SPEC = "eagle-eye-posterior-intelligence/1.0"
DEMO_REGISTRY_SEED = 20260712
DEMO_CUTOFF = "2025-04-22"


def quantize_micro(value: Any) -> Any:
    """Map every non-integer number to int(round-half-up(x * 1e6)).

    Deterministic and identical in verify.mjs: Math.floor(x * 1e6 + 0.5).
    Booleans/strings/None pass through; dict keys are untouched.
    """
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        # Integer-valued floats normalize to ints: JSON.parse in Node yields a
        # plain integer for "2.0", so both runtimes must see the same value.
        if value.is_integer():
            return int(value)
        return math.floor(value * 1_000_000 + 0.5)
    if isinstance(value, list):
        return [quantize_micro(item) for item in value]
    if isinstance(value, dict):
        return {key: quantize_micro(item) for key, item in value.items()}
    raise TypeError(f"unsupported type for quantization: {type(value)!r}")


def commitment_hash(value: Any) -> str:
    return sha256_hex(canonical_bytes(quantize_micro(value)))


def build_demo_registry() -> dict[str, Any]:
    world = generate_world(DEMO_REGISTRY_SEED, tasks_per_regime=16)
    return build_registry(world["tasks"])


def build_demo_target(fixture: dict[str, Any], *, cutoff: str = DEMO_CUTOFF) -> dict[str, Any]:
    """Derive the live PO-17 disruption target from the ingested fixture.

    Observations are deterministic functions of the fixture event (severity ->
    early delay signals), so the demo target is reproducible from fixture
    content alone and carries fixture provenance.
    """
    event = fixture["events"][0]
    po = fixture["purchase_orders"][0]
    severity = float(event.get("severity", 0.5))
    rng = DeterministicRng(stable_seed("demo-target", event["id"], po["id"], cutoff))
    cutoff_day = date.fromisoformat(cutoff)
    base = math.log(10.0) + 0.9 * severity
    observations = []
    for j in range(2):
        observations.append({
            "t": (cutoff_day - timedelta(days=2 * (2 - j))).isoformat(),
            "kind": "shipment_delay_signal",
            "log_delay_days": round(rng.normal(base, 0.18), 6),
            "source_id": event["source_id"],
        })
    value = float(po.get("value", 100000))
    return {
        "schema_version": SCHEMA_VERSION,
        "case_id": f"live-{event['id']}-{po['id']}",
        "tenant_id": "tenant-demo",
        "disruption_class": "port_congestion",
        "as_of_cutoff": cutoff,
        "entity_refs": {
            "supplier_id": event["supplier_id"],
            "component_id": fixture["components"][0]["id"],
            "purchase_order_id": po["id"],
            "lane": "asia-us-west",
            "region": "APAC",
            "exposure_rate_per_day_usd": round(value / 30.0, 2),
        },
        "observations": observations,
        "intervention": {"id": "wait_incumbent", "applied": False},
        "query": {
            "channels": ["delay", "stockout", "exposure", "recovery"],
            "delay_thresholds_days": [14, 21],
            "interval": 0.8,
        },
    }


def _strip_internal(prediction: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in prediction.items() if not key.startswith("_")}


def _calibration_receipt(court_receipt: dict[str, Any], candidate: str) -> dict[str, Any]:
    holdout = court_receipt["evaluations"][candidate]["holdout"]["metrics"]

    def micro(key: str) -> int | None:
        value = holdout.get(key)
        return None if value is None else math.floor(value * 1_000_000 + 0.5)

    receipt = {
        "source": "prediction-court",
        "court_receipt_id": court_receipt["court_receipt_id"],
        "holdout_sha256": court_receipt["holdout_sha256"],
        "candidate": candidate,
        "nll_micro": micro("nll"),
        "crps_micro": micro("crps"),
        "coverage80_micro": micro("coverage80"),
        "coverage_band_micro": [700000, 920000],
        "nll_temporal_ood_micro": micro("nll_temporal_ood"),
        "permutation_spread_max_micro": micro("permutation_spread_max"),
    }
    return receipt


def _recommendation(interventions: dict[str, Any]) -> dict[str, Any]:
    ranked = sorted(
        interventions.items(),
        key=lambda kv: (kv[1]["exposure_usd"]["quantiles_usd"]["p50"], kv[0]),
    )
    best_name, best = ranked[0]
    incumbent = interventions["wait_incumbent"]
    return {
        "recommended_intervention": best_name,
        "ranking": [name for name, _ in ranked],
        "expected_exposure_p50_usd": best["exposure_usd"]["quantiles_usd"]["p50"],
        "incumbent_exposure_p50_usd": incumbent["exposure_usd"]["quantiles_usd"]["p50"],
        "p_delay_exceeds_14_incumbent": incumbent["delay"]["p_exceeds_days"]["14"],
        "p_delay_exceeds_14_recommended": best["delay"]["p_exceeds_days"]["14"],
        "decision_basis": "median predicted exposure under each intervention; distributions shown, not point claims",
        "what_would_falsify": (
            "Realized delay outside the 80% interval, shift_score >= 0.8 on new "
            "target evidence, or a court re-run demoting the promoted candidate "
            "invalidates this recommendation."
        ),
    }


def attach_posterior_intelligence(
    run: dict[str, Any],
    *,
    registry: dict[str, Any],
    target: dict[str, Any],
    court_receipt: dict[str, Any],
    candidate: str = "governed_set_mt",
    k_max: int = 10,
) -> dict[str, Any]:
    """Attach the posterior block to `run` (mutates and returns run)."""
    if candidate != "governed_set_mt":
        raise ValueError("only the court-promoted governed candidate may serve predictions")
    decision = next(
        (d for d in court_receipt["decisions"] if d["candidate"] == candidate), None)
    if decision is None or decision["status"] != "promote":
        raise ValueError(f"candidate {candidate!r} has no promotion in the supplied court receipt")
    if court_receipt["registry_manifest_sha256"] != registry["manifest_sha256"]:
        raise ValueError("court receipt was measured against a different prior registry")

    selection = select_prior_tasks(registry, target, k_max=k_max)
    compiled = compile_prior_context(selection["included"], target)
    prediction = govern(predict_set_mt(compiled), compiled)
    prediction = _strip_internal(prediction)
    calibration = _calibration_receipt(court_receipt, candidate)

    abstained = prediction.get("interventions") is None
    interventions = prediction.get("interventions")
    block: dict[str, Any] = {
        "spec": POSTERIOR_SPEC,
        "engine_release": ENGINE_RELEASE,
        "generator_release": GENERATOR_RELEASE,
        "feature_schema_release": SCHEMA_VERSION,
        "tenant_id": target["tenant_id"],
        "case_id": target["case_id"],
        "disruption_class": target["disruption_class"],
        "as_of_cutoff": target["as_of_cutoff"],
        "prior_registry": {
            "release": registry["release"],
            "registry_release_id": registry["registry_release_id"],
            "manifest_sha256": registry["manifest_sha256"],
            "task_count": registry["task_count"],
        },
        "selection_receipt": selection["receipt"],
        "prior_manifest_sha256": compiled["prior_manifest_sha256"],
        "K": compiled["K"],
        "context_length": compiled["context_length"],
        "candidate": prediction["candidate"],
        "model_release": prediction["model_release"],
        "model_artifact_sha256": sha256_hex(canonical_bytes({
            "candidate": prediction["candidate"],
            "model_release": prediction["model_release"],
            "engine_release": ENGINE_RELEASE,
        })),
        "training_support": prediction["training_support"],
        "governed": prediction["governed"],
        "abstained": abstained,
        "interventions": interventions,
        "calibration_receipt": calibration,
        "calibration_receipt_sha256": sha256_hex(canonical_bytes(calibration)),
        "benchmark_court": {
            "court_receipt_id": court_receipt["court_receipt_id"],
            "development_sha256": court_receipt["development_sha256"],
            "holdout_sha256": court_receipt["holdout_sha256"],
            "decision": decision["status"],
        },
        "limitations": [
            "Prior tasks are authorized synthetic fixtures generated by " + GENERATOR_RELEASE + ".",
            "Distributions are calibrated against the sealed prediction court, not live operations.",
            "No external action is executed; recommendations require dual-control approval.",
        ],
    }
    basis = {
        "candidate": block["candidate"],
        "model_release": block["model_release"],
        "prior_manifest_sha256": block["prior_manifest_sha256"],
        "as_of_cutoff": block["as_of_cutoff"],
        "abstained": abstained,
        "interventions": interventions,
    }
    block["predictive_distribution_commitment"] = commitment_hash(basis)
    block["intervention_set_commitment"] = sha256_hex(
        canonical_bytes(sorted(interventions.keys()) if interventions else []))
    if interventions:
        block["recommendation"] = _recommendation(interventions)
    else:
        block["recommendation"] = {
            "recommended_intervention": None,
            "abstain_reason": prediction.get("abstain_reason"),
            "decision_basis": "engine abstained; no numbers are published outside validated support",
        }
    run["posterior_intelligence"] = block
    return run


def load_court_receipt(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"prediction court receipt missing at {path}; run scripts/run_prediction_court.py first")
    return json.loads(path.read_text())
