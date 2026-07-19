"""Verified feedback harness — the V7 recursive learning loop's sensor.

THE GAP THIS CLOSES: `generate_candidates` explored the mutation whitelist
UNIFORMLY at random — every run relearned nothing; blocked, rejected, and
promoted outcomes left no trace on the next round's search. The flywheel
spun; it did not climb.

THE INSTRUMENT: a signed, replayable FeedbackState of integer pseudo-weights
over the EXISTING mutation whitelist, updated by a pure function from
REVEALED, REPLAY-VERIFIED run outcomes only, and consumed by a deterministic
weighted candidate generator whose seed and candidate ids BIND the state
hash. "Haptic", because each sealed run's verified outcome is felt by the
next round's generation — pressure where evidence accumulated, release where
gates blocked.

INVARIANTS (all enforced by tests):
  - CONTAMINATION-CLOSED: updates consume only post-reveal bundles of PRIOR
    runs. A run's own sealed data cannot steer its own generation; the state
    hash is fixed before the run's secret is drawn.
  - SEARCH SPACE UNCHANGED: the whitelist and grids are imported, never
    extended; weights reorder exploration inside the same bounded space.
  - PROMOTION UNTOUCHED: gates, budgets, alpha accounting are not consulted
    or modified here. Better search cannot buy a weaker test.
  - NO STARVATION: every (key, value) keeps weight >= FLOOR_WEIGHT, so no
    region of the whitelist is ever unexplorable (mode-collapse guard).
  - REPLAYABLE: generation is a pure function of (decision core, state);
    candidate ids embed the state sha256, so an independent replay that
    recomputes generation from the recorded state must reproduce ids
    bit-for-bit — a forged or stale state changes every downstream id.
"""

from __future__ import annotations

import json
from typing import Any

from .evolution import (
    CHALLENGER_BUDGET_PER_CYCLE,
    COURT_RELEASE,
    MUTATION_WHITELIST,
    validate_mutation,
)
from .prior_registry import canonical_bytes, sha256_hex
from .stats import DeterministicRng, stable_seed

FEEDBACK_SPEC = "eagle-eye-feedback-harness/1.0"
FLOOR_WEIGHT = 1
REWARD_PROMOTED = 5
REWARD_NEAR_MISS = 2          # sealed look taken, challenger better, not significant
REWARD_EVIDENCE_STREAM = 1    # e-process stream with positive cumulative log-e
PENALTY_BLOCKED = 2           # trust/calibration/shift/contamination block


def _vkey(value: Any) -> str:
    """Canonical string key for a grid value (grids mix ints and strings)."""
    return json.dumps(value, sort_keys=True)


def genesis_state() -> dict[str, Any]:
    """Uniform pseudo-weights (=FLOOR_WEIGHT) over the whole whitelist."""
    return {
        "spec": FEEDBACK_SPEC,
        "updates_applied": 0,
        "weights": {
            key: {_vkey(v): FLOOR_WEIGHT for v in spec["grid"]}
            for key, spec in sorted(MUTATION_WHITELIST.items())
        },
    }


def state_sha256(state: dict[str, Any]) -> str:
    return sha256_hex(canonical_bytes(state))


def validate_state(state: dict[str, Any]) -> None:
    if state.get("spec") != FEEDBACK_SPEC:
        raise ValueError("feedback state spec mismatch")
    if set(state["weights"]) != set(MUTATION_WHITELIST):
        raise ValueError("feedback state keys do not match the mutation whitelist")
    for key, spec in MUTATION_WHITELIST.items():
        expected = {_vkey(v) for v in spec["grid"]}
        if set(state["weights"][key]) != expected:
            raise ValueError(f"feedback state grid mismatch for {key}")
        for vk, w in state["weights"][key].items():
            if not isinstance(w, int) or w < FLOOR_WEIGHT:
                raise ValueError(f"weight below floor or non-integer at {key}:{vk}")


def update_state(state: dict[str, Any], *, lineage_outcomes: list[dict[str, Any]],
                 evidence_standing: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """PURE state update from one revealed run.

    lineage_outcomes: [{"diff": {key: value}, "state": PROMOTION_STATE,
                        "mean_diff_micro": int | None}] drawn from the
    revealed bundle's lineage rows (single-key diffs by whitelist design).
    evidence_standing: current e-process standing rows ({"diff",
    "cumulative_log_e_micro"}); streams with positive cumulative evidence
    reinforce their (key, value).

    Returns a NEW state; the input is not mutated. Integer arithmetic only;
    weights never fall below FLOOR_WEIGHT.
    """
    validate_state(state)
    new_state = {
        "spec": state["spec"],
        "updates_applied": state["updates_applied"] + 1,
        "weights": {k: dict(v) for k, v in state["weights"].items()},
    }

    def bump(diff: dict[str, Any], delta: int) -> None:
        for key, value in diff.items():
            vk = _vkey(value)
            if key not in new_state["weights"] or vk not in new_state["weights"][key]:
                continue  # foreign diff: ignore, never widen the space
            new_state["weights"][key][vk] = max(
                FLOOR_WEIGHT, new_state["weights"][key][vk] + delta)

    for row in lineage_outcomes:
        outcome_state = row["state"]
        diff = row["diff"]
        if outcome_state == "PROMOTED":
            bump(diff, REWARD_PROMOTED)
        elif outcome_state == "REJECTED":
            mean = row.get("mean_diff_micro")
            if mean is not None and mean < 0:
                bump(diff, REWARD_NEAR_MISS)
        elif outcome_state.startswith("BLOCKED_"):
            bump(diff, -PENALTY_BLOCKED)
    for stream in evidence_standing or []:
        if stream.get("cumulative_log_e_micro", 0) > 0:
            bump(stream["diff"], REWARD_EVIDENCE_STREAM)
    validate_state(new_state)
    return new_state


def _weighted_index(rng: DeterministicRng, weights: list[int]) -> int:
    """Deterministic weighted choice via the shared DeterministicRng."""
    total = sum(weights)
    pick = rng.choice_index(total)
    acc = 0
    for i, w in enumerate(weights):
        acc += w
        if pick < acc:
            return i
    return len(weights) - 1  # unreachable with positive weights


def weighted_generate_candidates(*, run_seed: int, champion_id: str,
                                 champion_config: dict[str, Any], snapshot_id: str,
                                 registry_manifest_sha256: str,
                                 evaluator_seed_commitment: str, cycle: int,
                                 feedback_state: dict[str, Any],
                                 budget: int = CHALLENGER_BUDGET_PER_CYCLE) -> list[dict[str, Any]]:
    """Feedback-weighted counterpart of `evolution.generate_candidates`.

    Same whitelist, same grids, same budget, same champion/seq skip rules,
    same snapshot binding — only the exploration DISTRIBUTION changes, and
    the generation seed and every candidate id additionally bind the
    feedback state hash, so replay recomputation is exact and any state
    substitution is detectable.
    """
    validate_state(feedback_state)
    state_sha = state_sha256(feedback_state)
    rng = DeterministicRng(stable_seed("evolve-feedback", run_seed, champion_id,
                                       registry_manifest_sha256, evaluator_seed_commitment,
                                       COURT_RELEASE, cycle, budget, state_sha))
    names = sorted(MUTATION_WHITELIST)
    key_weights = [sum(feedback_state["weights"][n].values()) for n in names]
    out, seen, attempts = [], set(), 0
    while len(out) < budget and attempts < budget * 12:
        attempts += 1
        name = names[_weighted_index(rng, key_weights)]
        spec = MUTATION_WHITELIST[name]
        grid = spec["grid"]
        value_weights = [feedback_state["weights"][name][_vkey(v)] for v in grid]
        value = grid[_weighted_index(rng, value_weights)]
        if value == champion_config[name]:
            continue
        if name.startswith("seq.") and champion_config["base.candidate"] == "set_mt":
            continue
        diff = {name: value}
        key = json.dumps(diff, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        validate_mutation(diff)
        out.append({
            "candidate_id": "cand-" + sha256_hex(canonical_bytes(
                {"p": champion_id, "d": diff, "c": cycle, "snap": snapshot_id,
                 "fb": state_sha}))[:12],
            "parent_champion_id": champion_id,
            "mutation_type": "typed_parameter", "diff": diff,
            "config": {**champion_config, **diff},
            "hypothesis": f"adjusting {name} to {value} improves sealed paired log score without regression",
            "expected_benefit": "sharper or better-supported posterior",
            "known_risk": "calibration or OoD regression; support misuse",
            "generation_seed": run_seed,
            "dataset_snapshot_id": snapshot_id,
            "court_release_id": COURT_RELEASE,
            "candidate_budget_position": len(out) + 1,
            "created_at_cycle": cycle,
            "feedback_state_sha256": state_sha,
        })
    return out


def lineage_outcomes_from_bundle(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the harness's inputs from a revealed bundle's lineage rows."""
    out = []
    for row in bundle["chains"]["lineage"]["rows"]:
        body = row["body"]
        stats = body.get("statistics") or {}
        out.append({
            "diff": body["candidate"]["diff"],
            "state": body["state"],
            "mean_diff_micro": stats.get("mean_diff_micro"),
        })
    return out
