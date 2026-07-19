"""Prior Task Selector and Prior Context Compiler.

Selection uses only cutoff-valid information and emits a deterministic
inclusion/exclusion receipt. Compilation preserves strict task boundaries:

    <prior> D1 ... <prior> DK  <target> current observations + query

Prior observations are NEVER pooled into the target block; the compiled
context carries a manifest hash so the exact prior prefix is committed into
the evidence chain.
"""

from __future__ import annotations

from typing import Any

from .prior_registry import canonical_bytes, sha256_hex, tasks_visible_at

SELECTOR_RELEASE = "prior-selector/1.0"
COMPILER_RELEASE = "prior-compiler/1.0"


def _similarity(task: dict[str, Any], target: dict[str, Any]) -> tuple[float, list[str]]:
    """Deterministic cutoff-valid similarity score with reason codes."""
    score = 0.0
    reasons: list[str] = []
    if task["disruption_class"] == target["disruption_class"]:
        score += 4.0
        reasons.append("class_match")
    refs_t, refs_g = task["entity_refs"], target["entity_refs"]
    if refs_t.get("lane") == refs_g.get("lane"):
        score += 1.5
        reasons.append("lane_match")
    if refs_t.get("region") == refs_g.get("region"):
        score += 1.0
        reasons.append("region_match")
    if refs_t.get("supplier_id") == refs_g.get("supplier_id"):
        score += 1.0
        reasons.append("supplier_match")
    # Recency: newer closed tasks carry more regime information.
    score += 0.5 if task["as_of_end"] >= "2025-01-01" else 0.0
    if task["observations"]:
        reasons.append("has_observations")
        score += 0.25
    return score, reasons


def select_prior_tasks(
    registry: dict[str, Any],
    target: dict[str, Any],
    *,
    k_max: int = 12,
    min_score: float = 4.0,
    require_class_match: bool = True,
) -> dict[str, Any]:
    """Select comparable-but-separate historical tasks for the target.

    Hard boundaries first (tenant, as-of), then deterministic similarity
    ranking. Returns included tasks and a receipt that names every considered
    task with its decision and reason codes.
    """
    boundary = tasks_visible_at(
        registry,
        tenant_id=target["tenant_id"],
        as_of_cutoff=target["as_of_cutoff"],
    )
    # Receipt numbers are integer milli-scores so that BOTH verifier runtimes
    # (Python and Node) can recompute the receipt hash from re-serialized
    # canonical JSON without float-representation drift.
    decisions: list[dict[str, Any]] = [
        {"task_id": row["task_id"], "decision": "excluded", "reasons": [row["reason"]], "score_milli": None}
        for row in boundary["exclusion_receipt"]["excluded"]
    ]

    def _milli(score: float) -> int:
        return int(round(score * 1000.0))

    scored: list[tuple[float, dict[str, Any], list[str]]] = []
    for task in boundary["visible"]:
        score, reasons = _similarity(task, target)
        if require_class_match and task["disruption_class"] != target["disruption_class"]:
            decisions.append({"task_id": task["task_id"], "decision": "excluded",
                              "reasons": ["class_mismatch"], "score_milli": _milli(score)})
            continue
        if score < min_score:
            decisions.append({"task_id": task["task_id"], "decision": "excluded",
                              "reasons": reasons + ["below_min_score"], "score_milli": _milli(score)})
            continue
        scored.append((score, task, reasons))
    # Deterministic order: score desc, then most recently closed, then id.
    scored.sort(key=lambda row: (-row[0], row[1]["as_of_end"], row[1]["task_id"]))
    included = scored[:k_max]
    for score, task, reasons in included:
        decisions.append({"task_id": task["task_id"], "decision": "included",
                          "reasons": reasons, "score_milli": _milli(score)})
    for score, task, reasons in scored[k_max:]:
        decisions.append({"task_id": task["task_id"], "decision": "excluded",
                          "reasons": reasons + ["k_max_reached"], "score_milli": _milli(score)})
    decisions.sort(key=lambda row: row["task_id"])
    receipt = {
        "selector_release": SELECTOR_RELEASE,
        "registry_release_id": registry["registry_release_id"],
        "registry_manifest_sha256": registry["manifest_sha256"],
        "tenant_id": target["tenant_id"],
        "as_of_cutoff": target["as_of_cutoff"],
        "k_max": k_max,
        "min_score_milli": _milli(min_score),
        "require_class_match": require_class_match,
        "included_prior_task_ids": [task["task_id"] for _, task, _ in included],
        "decisions": decisions,
    }
    receipt["receipt_sha256"] = sha256_hex(canonical_bytes(receipt))
    return {"included": [task for _, task, _ in included], "receipt": receipt}


class CompilerError(ValueError):
    """Raised when compilation would violate prior/target separation."""


def compile_prior_context(included: list[dict[str, Any]], target: dict[str, Any]) -> dict[str, Any]:
    """Compile the paper's prefix structure with strict boundary preservation."""
    target_cutoff = target["as_of_cutoff"]
    blocks: list[dict[str, Any]] = []
    for task in included:
        if task["as_of_end"] > target_cutoff:
            raise CompilerError(
                f"prior task {task['task_id']} closes after target cutoff {target_cutoff} (temporal leakage)"
            )
        if task["tenant_id"] != target["tenant_id"]:
            raise CompilerError(
                f"prior task {task['task_id']} belongs to tenant {task['tenant_id']!r}, "
                f"target belongs to {target['tenant_id']!r} (tenant boundary)"
            )
        blocks.append({
            "boundary": "prior",
            "task_id": task["task_id"],
            "disruption_class": task["disruption_class"],
            "intervention_id": task["intervention"]["id"],
            "observations": [obs["log_delay_days"] for obs in task["observations"]],
            "realized": {
                "log_final_delay": task["realized"]["log_final_delay"],
                "stockout": task["realized"]["stockout"],
                "intervention_success": task["realized"]["intervention_success"],
            },
        })
    target_observations = [obs["log_delay_days"] for obs in target["observations"]]
    for obs in target["observations"]:
        if obs["t"] > target_cutoff:
            raise CompilerError(f"target observation at {obs['t']} is after cutoff {target_cutoff}")
    target_block = {
        "boundary": "target",
        "case_id": target["case_id"],
        "disruption_class": target["disruption_class"],
        "observations": target_observations,
        "exposure_rate_per_day_usd": target["entity_refs"]["exposure_rate_per_day_usd"],
        "query": target["query"],
    }
    prior_manifest = [
        {"task_id": block["task_id"], "n_obs": len(block["observations"])} for block in blocks
    ]
    compiled = {
        "compiler_release": COMPILER_RELEASE,
        "prior_blocks": blocks,
        "target_block": target_block,
        "K": len(blocks),
        "context_length": sum(len(b["observations"]) + 1 for b in blocks) + len(target_observations),
        "prior_manifest": prior_manifest,
        "prior_manifest_sha256": sha256_hex(canonical_bytes(prior_manifest)),
    }
    # Post-condition: target observations must not appear inside prior blocks
    # (guards against future refactors accidentally pooling).
    for block in compiled["prior_blocks"]:
        if block["observations"] is target_observations:
            raise CompilerError("prior block aliases target observations (pooling bug)")
    return compiled
