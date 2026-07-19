"""Shared flywheel cycle functions (V4).

`commit_cycle_prediction` and `calibration_pairs` are used verbatim by BOTH
the live benchmark (scripts/run_sealed_evolution.py) and the independent
full-decision replay (scripts/replay_sealed_evolution.py), so a committed
prediction block — and therefore its distribution commitment, prediction id,
and downstream resolution hash chain — is bit-for-bit recomputable from the
replay bundle's public seeds and configs.
"""

from __future__ import annotations

from typing import Any

from .evolution import predictor_from_config
from .posterior_engine import commitment_hash
from .prior_selector import compile_prior_context, select_prior_tasks


def commit_cycle_prediction(registry: dict[str, Any], target: dict[str, Any],
                            config: dict[str, Any], champion_id: str) -> dict[str, Any]:
    selection = select_prior_tasks(registry, target, k_max=config["selector.k_max"],
                                   min_score=config["selector.min_score_milli"] / 1000.0)
    compiled = compile_prior_context(selection["included"], target)
    prediction = predictor_from_config(config)(compiled)
    prediction = {k: v for k, v in prediction.items() if not k.startswith("_")}
    abstained = prediction.get("interventions") is None
    interventions = prediction.get("interventions")
    if interventions:
        ranked = sorted(interventions.items(),
                        key=lambda kv: (kv[1]["exposure_usd"]["quantiles_usd"]["p50"], kv[0]))
        recommendation = {"recommended_intervention": ranked[0][0], "ranking": [n for n, _ in ranked]}
    else:
        recommendation = {"recommended_intervention": None}
    basis = {"candidate": prediction["candidate"], "model_release": prediction["model_release"],
             "prior_manifest_sha256": compiled["prior_manifest_sha256"],
             "as_of_cutoff": target["as_of_cutoff"], "abstained": abstained,
             "interventions": interventions}
    return {
        "case_id": target["case_id"], "tenant_id": target["tenant_id"],
        "as_of_cutoff": target["as_of_cutoff"], "abstained": abstained,
        "candidate": prediction["candidate"], "model_release": prediction["model_release"],
        "champion_id": champion_id, "governed": prediction["governed"],
        "diagnostics": prediction.get("diagnostics", {}),
        "K": compiled["K"], "prior_manifest_sha256": compiled["prior_manifest_sha256"],
        "disruption_class": target["disruption_class"],
        "selection_receipt": selection["receipt"], "interventions": interventions,
        "recommendation": recommendation,
        "predictive_distribution_commitment": commitment_hash(basis),
    }


def calibration_pairs(registry: dict[str, Any], config: dict[str, Any],
                      suite: dict[str, Any]) -> list[tuple]:
    from .predictors import LogScaleDist
    fn = predictor_from_config(config)
    pairs = []
    for row in suite["cases"]:
        selection = select_prior_tasks(registry, row["target"], k_max=config["selector.k_max"],
                                       min_score=config["selector.min_score_milli"] / 1000.0)
        compiled = compile_prior_context(selection["included"], row["target"])
        prediction = fn(compiled)
        if prediction.get("interventions") is None:
            continue
        payload = prediction["interventions"]["wait_incumbent"]["delay"]
        pairs.append((row["truth"]["outcomes"]["wait_incumbent"]["log_final_delay"],
                      LogScaleDist(payload["loc"], payload["scale"], payload["df"]),
                      row["subset"]))
    return pairs
