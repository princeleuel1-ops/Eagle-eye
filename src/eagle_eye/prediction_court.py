"""Sealed probabilistic evaluation court for the disruption engine.

Development and holdout suites are generated from DIFFERENT world seeds and
sealed by content hash before any candidate is scored. Holdout embeds the
attack battery: temporal OoD (regime shift), heavy tails, target scarcity,
K-extrapolation probes, unrelated-class priors, permutation stress, leakage
and tenant-boundary attacks.

Promotion rule (all gates must pass against the no_prefix baseline):
  sealed proper-scoring improvement (NLL and CRPS on holdout)
  AND calibration acceptable (coverage@80 within tolerance)
  AND temporal OoD non-worse
  AND leakage + tenant + contamination checks pass
  AND permutation spread within tolerance
  AND abstention correctness (abstain on out-of-support probes, never on standard cases)
  AND latency within budget
Latency is measured but excluded from the deterministic receipt id.
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Callable

from .governor import govern
from .predictors import (
    LogScaleDist,
    predict_climatology,
    predict_naive_pooling,
    predict_no_prefix,
    predict_oracle_hier,
    predict_oracle_true,
    predict_seq_prefix,
    predict_set_mt,
)
from .prior_registry import build_registry, canonical_bytes, sha256_hex
from .prior_selector import CompilerError, compile_prior_context, select_prior_tasks
from .regimes import generate_target_case, generate_world
from .stats import DeterministicRng, brier, log_sum_exp, stable_seed

COURT_SPEC = "eagle-eye-prediction-court/1.0"
PERMUTATION_ROUNDS = 6
LATENCY_BUDGET_MS = 50.0
COVERAGE_BAND = (0.70, 0.92)
PERMUTATION_TOLERANCE = 0.05
OOD_TOLERANCE_NATS = 0.0  # non-worse means non-worse

# Attack subsets: abstention is permitted (and for k probes REQUIRED — a
# promotable candidate must refuse predictions outside validated support).
ATTACK_SUBSETS = {"k_probe_beyond", "unrelated_priors"}


# ---------------------------------------------------------------------------
# Candidate wiring
# ---------------------------------------------------------------------------

def predict_seq_prefix_overfit(compiled: dict[str, Any]) -> dict[str, Any]:
    """Engineered attractive regression: aggressive recency + confidence boost
    tuned to shine on IID development cases. Expected to fail sealed gates."""
    prediction = predict_seq_prefix(compiled, decay=0.35)
    base: LogScaleDist = prediction["_delay_dist"]
    sharpened = LogScaleDist(base.loc, base.scale * 0.40, base.df)
    prediction = dict(prediction)
    prediction["candidate"] = "seq_prefix_overfit"
    prediction["model_release"] = "seq-prefix-overfit/9.0"
    prediction["_delay_dist"] = sharpened
    prediction["diagnostics"] = {**prediction.get("diagnostics", {}),
                                 "note": "dev-tuned sharpening x0.40; recency decay 0.35"}
    return prediction


def predict_governed_set_mt(compiled: dict[str, Any]) -> dict[str, Any]:
    return govern(predict_set_mt(compiled), compiled)


COURT_CANDIDATES: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "climatology": predict_climatology,
    "no_prefix": predict_no_prefix,
    "naive_pooling": predict_naive_pooling,
    "seq_prefix": predict_seq_prefix,
    "set_mt": predict_set_mt,
    "governed_set_mt": predict_governed_set_mt,
    "seq_prefix_overfit": predict_seq_prefix_overfit,
}

BASELINE_CANDIDATE = "no_prefix"


# ---------------------------------------------------------------------------
# Suite construction (sealed)
# ---------------------------------------------------------------------------

def _case_rows(world: dict[str, Any], plan: list[dict[str, Any]],
               *, index_offset: int = 0) -> list[dict[str, Any]]:
    rows = []
    for index, spec in enumerate(plan):
        result = generate_target_case(
            world,
            case_index=1000 + index + index_offset,
            tenant_id="tenant-demo",
            disruption_class=spec["disruption_class"],
            cutoff=spec["cutoff"],
            n_target_obs=spec["n_target_obs"],
        )
        rows.append({
            "subset": spec["subset"],
            "k_max": spec.get("k_max", 10),
            "target": result["target"],
            "truth": result["truth"],
        })
    return rows


def build_development_suite(seed: int = 11) -> dict[str, Any]:
    world = generate_world(seed, tasks_per_regime=16)
    rng = DeterministicRng(stable_seed("dev-plan", seed))
    plan = []
    cutoffs = ["2025-02-10", "2025-03-15", "2025-04-20", "2025-05-25"]
    for disruption_class in ("port_congestion", "supplier_quality"):
        for cutoff in cutoffs:
            for n_obs in (1, 2, 4):
                plan.append({"subset": "iid", "disruption_class": disruption_class,
                             "cutoff": cutoff, "n_target_obs": n_obs})
    for cutoff in cutoffs[:2]:
        for n_obs in (2, 4):
            plan.append({"subset": "iid", "disruption_class": "geopolitical",
                         "cutoff": cutoff, "n_target_obs": n_obs})
    _ = rng  # reserved for future plan randomization; kept for seed stability
    return {"suite": "development", "world_seed": seed, "cases": _case_rows(world, plan),
            "world": world}


def build_holdout_suite(seed: int = 202607, *, scale: int = 1) -> dict[str, Any]:
    world = generate_world(seed, tasks_per_regime=16)
    plan = []
    # IID-like sealed subset (same regimes, unseen seed)
    for cutoff in ("2025-02-20", "2025-04-05", "2025-06-01"):
        for disruption_class in ("port_congestion", "supplier_quality"):
            for n_obs in (1, 2, 4):
                plan.append({"subset": "iid", "disruption_class": disruption_class,
                             "cutoff": cutoff, "n_target_obs": n_obs})
    # Temporal OoD: targets shortly after the port-congestion regime shift;
    # closed priors are still dominated by the pre-shift regime.
    for cutoff in ("2025-08-05", "2025-09-10"):
        for n_obs in (0, 1, 2, 4):
            plan.append({"subset": "temporal_ood", "disruption_class": "port_congestion",
                         "cutoff": cutoff, "n_target_obs": n_obs})
    # Heavy tails (df=3 regime)
    for cutoff in ("2025-03-01", "2025-05-15"):
        for n_obs in (1, 2, 4, 6):
            plan.append({"subset": "heavy_tail", "disruption_class": "geopolitical",
                         "cutoff": cutoff, "n_target_obs": n_obs})
    # Target scarcity
    for cutoff in ("2025-03-20", "2025-05-05"):
        for n_obs in (0, 0, 1, 1):
            plan.append({"subset": "scarcity", "disruption_class": "port_congestion",
                         "cutoff": cutoff, "n_target_obs": n_obs})
    # K extrapolation probes (k_max beyond declared training support)
    for n_obs in (1, 2):
        plan.append({"subset": "k_probe_beyond", "disruption_class": "port_congestion",
                     "cutoff": "2025-05-20", "n_target_obs": n_obs, "k_max": 30})
    # Unrelated-class priors (measured negative transfer, informational)
    for n_obs in (1, 2):
        plan.append({"subset": "unrelated_priors", "disruption_class": "port_congestion",
                     "cutoff": "2025-04-15", "n_target_obs": n_obs})
    # V4 (audit blocker 6): scaling is honest sample-size scaling ONLY —
    # every replica reuses the EXACT plan (same subsets, disruption classes,
    # cutoffs, n_target_obs, k_max) but draws INDEPENDENT case identities via
    # a disjoint case-index block. The V3 behavior (incrementing n_target_obs
    # per replica) changed the stratum composition and is WITHDRAWN.
    cases = _case_rows(world, plan)
    for replica in range(1, max(1, scale)):
        cases.extend(_case_rows(world, plan, index_offset=replica * 100_000))
    return {"suite": "holdout", "world_seed": seed, "cases": cases,
            "world": world, "scale": max(1, scale), "stratum_plan_size": len(plan)}


def _visible_and_truth(suite: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Canonical split of a suite into predictor-visible cases and truth."""
    visible = {
        "suite": suite["suite"],
        "world_seed": suite["world_seed"],
        "cases": [
            {"subset": row["subset"], "k_max": row["k_max"], "target": row["target"]}
            for row in suite["cases"]
        ],
    }
    truth = {
        "suite": suite["suite"],
        "truth": [
            {"case_id": row["target"]["case_id"], "truth": row["truth"]}
            for row in suite["cases"]
        ],
    }
    return visible, truth


def suite_manifest(suite: dict[str, Any]) -> dict[str, Any]:
    """Pure content commitment for a suite: case count + canonical hashes of
    the visible cases and of the truth. Used by the sealed evaluator to commit
    to its private suites BEFORE any look, and by the independent replay to
    prove the rebuilt suites are bit-identical to the committed ones."""
    visible, truth = _visible_and_truth(suite)
    return {
        "case_count": len(suite["cases"]),
        "world_seed": suite["world_seed"],
        "scale": suite.get("scale", 1),
        "cases_sha256": sha256_hex(canonical_bytes(visible)),
        "truth_sha256": sha256_hex(canonical_bytes(truth)),
    }


def seal_suite(suite: dict[str, Any], path: Path) -> dict[str, Any]:
    """Write the predictor-visible part of the suite and hash it. Truth stays
    in a sibling file whose hash is also recorded (oracle/scoring only)."""
    visible, truth = _visible_and_truth(suite)
    path.parent.mkdir(parents=True, exist_ok=True)
    visible_bytes = json.dumps(visible, indent=2, sort_keys=True).encode()
    truth_bytes = json.dumps(truth, indent=2, sort_keys=True).encode()
    path.write_bytes(visible_bytes)
    truth_path = path.with_name(path.name.replace(".json", "-truth.json"))
    truth_path.write_bytes(truth_bytes)
    return {
        "cases_path": str(path),
        "truth_path": str(truth_path),
        "cases_sha256": sha256_hex(visible_bytes),
        "truth_sha256": sha256_hex(truth_bytes),
        "case_count": len(suite["cases"]),
    }


def contamination_check(dev: dict[str, Any], holdout: dict[str, Any]) -> dict[str, Any]:
    def fingerprints(suite: dict[str, Any]) -> set[str]:
        prints = set()
        for row in suite["cases"]:
            body = {k: v for k, v in row["target"].items() if k != "case_id"}
            prints.add(sha256_hex(canonical_bytes(body)))
        return prints

    dev_ids = {row["target"]["case_id"] for row in dev["cases"]}
    holdout_ids = {row["target"]["case_id"] for row in holdout["cases"]}
    id_overlap = sorted(dev_ids & holdout_ids)
    content_overlap = fingerprints(dev) & fingerprints(holdout)
    seed_distinct = dev["world_seed"] != holdout["world_seed"]
    detected = bool(id_overlap or content_overlap or not seed_distinct)
    return {
        "id_overlap": id_overlap,
        "content_overlap_count": len(content_overlap),
        "world_seeds_distinct": seed_distinct,
        "contamination_detected": detected,
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def scored_dist(prediction: dict[str, Any], intervention: str) -> LogScaleDist:
    base: LogScaleDist = prediction["_delay_dist"]
    effect = prediction["_effects"][intervention]
    return base.shifted(effect["delta"], effect["var"])


def _kl_to_oracle(candidate: LogScaleDist, oracle: LogScaleDist, *, n_grid: int = 240) -> float:
    """KL(candidate || oracle) by deterministic quadrature on log-delay."""
    lo = min(candidate.loc - 8 * candidate.scale, oracle.loc - 8 * oracle.scale)
    hi = max(candidate.loc + 8 * candidate.scale, oracle.loc + 8 * oracle.scale)
    h = (hi - lo) / n_grid
    total = 0.0
    for i in range(n_grid + 1):
        x = lo + i * h
        weight = 0.5 if i in (0, n_grid) else 1.0
        lp_c = candidate.logpdf(x)
        total += weight * math.exp(lp_c) * (lp_c - oracle.logpdf(x))
    return max(0.0, total * h)


def _permutation_spread(fn: Callable[[dict[str, Any]], dict[str, Any]],
                        compiled: dict[str, Any], case_seed: int) -> float:
    """Max |Δ median log-delay| across deterministic prior-order permutations."""
    locs = []
    blocks = compiled["prior_blocks"]
    for round_index in range(PERMUTATION_ROUNDS):
        rng = DeterministicRng(stable_seed("perm", case_seed, round_index))
        order = list(range(len(blocks)))
        for i in range(len(order) - 1, 0, -1):
            j = rng.choice_index(i + 1)
            order[i], order[j] = order[j], order[i]
        shuffled = dict(compiled)
        shuffled["prior_blocks"] = [blocks[i] for i in order]
        prediction = fn(shuffled)
        if prediction.get("interventions") is None:
            continue
        locs.append(scored_dist(prediction, "wait_incumbent").loc)
    if len(locs) < 2:
        return 0.0
    return max(locs) - min(locs)


def _expected_delay_days(theta: float, hyper: dict[str, Any], intervention: str) -> float:
    cfg = hyper["interventions"][intervention]
    variance = cfg["d_sd"] ** 2 + hyper["sigma"] ** 2
    return math.exp(theta + cfg["d_mean"] + 0.5 * variance)


def _intervention_regret(prediction: dict[str, Any], truth: dict[str, Any]) -> float:
    """Exposure regret (USD-normalized to rate 1.0) of the candidate's pick
    under the TRUE expected delays. 0 = picked the truly best intervention."""
    hyper, theta = truth["hyper"], truth["theta"]
    true_expected = {name: _expected_delay_days(theta, hyper, name) for name in hyper["interventions"]}
    best = min(true_expected.values())
    picks = {
        name: payload["delay"]["quantiles_days"]["p50"]
        for name, payload in prediction["interventions"].items()
    }
    chosen = min(picks, key=lambda name: picks[name])
    return true_expected[chosen] - best


def evaluate_candidate_on_suite(name: str, suite: dict[str, Any], registry: dict[str, Any],
                                *, permutation_subset: str = "iid",
                                fn: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
                                k_max_override: int | None = None,
                                min_score_override: float | None = None) -> dict[str, Any]:
    fn = fn or COURT_CANDIDATES[name]
    per_case: list[dict[str, Any]] = []
    latencies: list[float] = []
    abstentions_standard = 0
    abstentions_probe = 0
    probe_count = 0
    permutation_spreads: list[float] = []
    leak_defenses = 0

    for row in suite["cases"]:
        target, truth = row["target"], row["truth"]
        if row["subset"] == "unrelated_priors":
            # Adversarial context: force a full-K prefix of wrong-class tasks so
            # negative transfer is actually measured (not an empty context).
            selection = select_prior_tasks(registry, target, k_max=999,
                                           require_class_match=False, min_score=0.5)
            included = [t for t in selection["included"]
                        if t["disruption_class"] != target["disruption_class"]][: row["k_max"]]
        else:
            # Attack subsets (e.g. k probes) keep their forced parameters:
            # a mutation must never be able to defuse an attack row.
            is_attack = row["subset"] in ATTACK_SUBSETS
            selection = select_prior_tasks(
                registry, target,
                k_max=row["k_max"] if (is_attack or k_max_override is None) else k_max_override,
                min_score=4.0 if (is_attack or min_score_override is None) else min_score_override)
            included = selection["included"]
        # Leakage self-check: recompute boundary on every included task.
        assert all(t["as_of_end"] <= target["as_of_cutoff"] for t in included)
        assert all(t["tenant_id"] == target["tenant_id"] for t in included)
        compiled = compile_prior_context(included, target)
        start = time.perf_counter()
        prediction = fn(compiled)
        latencies.append((time.perf_counter() - start) * 1000.0)

        is_probe = row["subset"] == "k_probe_beyond"
        probe_count += 1 if is_probe else 0
        # V4: a malformed response (no 'interventions' key at all) is NOT an
        # abstention — abstention is an explicit governed refusal with the key
        # present and None. Malformed responses raise and, inside the sealed
        # evaluator, terminate the charged look as FAILED.
        if not isinstance(prediction, dict) or "interventions" not in prediction:
            raise ValueError(
                f"malformed candidate response for case {target['case_id']}: "
                "missing 'interventions' (explicit None required to abstain)")
        if prediction.get("interventions") is None:
            if is_probe:
                abstentions_probe += 1
            elif row["subset"] not in ATTACK_SUBSETS:
                abstentions_standard += 1
            per_case.append({"case_id": target["case_id"], "subset": row["subset"], "abstained": True})
            continue

        realized = truth["outcomes"]["wait_incumbent"]
        dist = scored_dist(prediction, "wait_incumbent")
        y = realized["log_final_delay"]
        lo = dist.ppf(0.10)
        hi = dist.ppf(0.90)
        oracle = predict_oracle_hier(compiled, truth["hyper"])
        oracle_dist = scored_dist(oracle, "wait_incumbent")
        kl = _kl_to_oracle(dist, oracle_dist) if truth["hyper"]["heavy_tail_df"] is None else None
        stock_p = prediction["interventions"]["wait_incumbent"]["stockout"]["p"]
        record = {
            "case_id": target["case_id"],
            "subset": row["subset"],
            "abstained": False,
            "nll": -dist.logpdf(y),
            "crps": dist.crps(y),
            "covered80": bool(lo <= y <= hi),
            "width80_log": hi - lo,
            "brier_delay_gt14": brier(1.0 - dist.cdf(math.log(14.0)), realized["final_delay_days"] > 14.0),
            "brier_stockout": brier(stock_p, bool(realized["stockout"])),
            "kl_to_oracle": kl,
            "intervention_regret_days": _intervention_regret(prediction, truth),
        }
        per_case.append(record)
        if row["subset"] == permutation_subset and len(compiled["prior_blocks"]) >= 4 and len(permutation_spreads) < 8:
            permutation_spreads.append(
                _permutation_spread(fn, compiled, stable_seed("case", target["case_id"])))

    scored = [r for r in per_case if not r["abstained"]]

    def _mean(key: str, subset: str | None = None) -> float | None:
        rows = [r[key] for r in scored
                if (subset is None or r["subset"] == subset) and r.get(key) is not None]
        return round(sum(rows) / len(rows), 6) if rows else None

    return {
        "candidate": name,
        "suite": suite["suite"],
        "case_count": len(suite["cases"]),
        "scored_count": len(scored),
        "abstentions_standard": abstentions_standard,
        "abstentions_probe": abstentions_probe,
        "probe_count": probe_count,
        "metrics": {
            "nll": _mean("nll"),
            "crps": _mean("crps"),
            "coverage80": _mean("covered80"),
            "width80_log": _mean("width80_log"),
            "brier_delay_gt14": _mean("brier_delay_gt14"),
            "brier_stockout": _mean("brier_stockout"),
            "kl_to_oracle": _mean("kl_to_oracle"),
            "intervention_regret_days": _mean("intervention_regret_days"),
            "nll_temporal_ood": _mean("nll", "temporal_ood"),
            "crps_temporal_ood": _mean("crps", "temporal_ood"),
            "nll_heavy_tail": _mean("nll", "heavy_tail"),
            "nll_scarcity": _mean("nll", "scarcity"),
            "crps_scarcity": _mean("crps", "scarcity"),
            "nll_unrelated_priors": _mean("nll", "unrelated_priors"),
            "permutation_spread_max": round(max(permutation_spreads), 6) if permutation_spreads else 0.0,
        },
        "latency_ms_mean": round(sum(latencies) / len(latencies), 3),
        "per_case": per_case,
    }


# ---------------------------------------------------------------------------
# Promotion court
# ---------------------------------------------------------------------------

def leakage_attack_battery(registry: dict[str, Any], suite: dict[str, Any]) -> dict[str, Any]:
    """Direct attacks on the boundary layer; all must be refused."""
    row = suite["cases"][0]
    target = row["target"]
    selection = select_prior_tasks(registry, target, k_max=6)
    defenses = {}
    leaky = dict(selection["included"][0])
    leaky = json.loads(json.dumps(leaky))
    leaky["as_of_end"] = "2031-01-01"
    try:
        compile_prior_context([leaky], target)
        defenses["future_task_refused"] = False
    except CompilerError:
        defenses["future_task_refused"] = True
    foreign = json.loads(json.dumps(selection["included"][0]))
    foreign["tenant_id"] = "tenant-mallory"
    try:
        compile_prior_context([foreign], target)
        defenses["foreign_tenant_refused"] = False
    except CompilerError:
        defenses["foreign_tenant_refused"] = True
    boundary = select_prior_tasks(registry, target, k_max=999)
    defenses["selector_no_future_tasks"] = all(
        t["as_of_end"] <= target["as_of_cutoff"] for t in boundary["included"])
    defenses["selector_no_foreign_tenants"] = all(
        t["tenant_id"] == target["tenant_id"] for t in boundary["included"])
    defenses["all_defended"] = all(defenses.values())
    return defenses


def promotion_decision(candidate: dict[str, Any], baseline: dict[str, Any],
                       *, leakage: dict[str, Any], contamination: dict[str, Any]) -> dict[str, Any]:
    m_c, m_b = candidate["metrics"], baseline["metrics"]
    gates = {
        "proper_scoring_improved": m_c["nll"] < m_b["nll"] and m_c["crps"] < m_b["crps"],
        "calibration_acceptable": COVERAGE_BAND[0] <= (m_c["coverage80"] or 0.0) <= COVERAGE_BAND[1],
        "temporal_ood_non_worse": (
            m_c["nll_temporal_ood"] is None or m_b["nll_temporal_ood"] is None
            or m_c["nll_temporal_ood"] <= m_b["nll_temporal_ood"] + OOD_TOLERANCE_NATS
        ),
        "leakage_defended": leakage["all_defended"],
        "no_contamination": not contamination["contamination_detected"],
        "permutation_within_tolerance": m_c["permutation_spread_max"] <= PERMUTATION_TOLERANCE,
        "no_standard_abstention": candidate["abstentions_standard"] == 0,
        "out_of_support_refused": (
            candidate["probe_count"] == 0
            or candidate["abstentions_probe"] == candidate["probe_count"]
        ),
        "latency_within_budget": candidate["latency_ms_mean"] <= LATENCY_BUDGET_MS,
        "external_execution_false": True,
    }
    reasons = [gate for gate, passed in gates.items() if not passed]
    return {
        "candidate": candidate["candidate"],
        "status": "promote" if not reasons else "reject",
        "gates": gates,
        "reasons": reasons,
    }


def run_prediction_court(output_dir: Path, *, dev_seed: int = 11, holdout_seed: int = 202607,
                         registry_seed: int = 20260712) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    registry_world = generate_world(registry_seed, tasks_per_regime=16)
    registry = build_registry(registry_world["tasks"])

    development = build_development_suite(dev_seed)
    holdout = build_holdout_suite(holdout_seed)
    dev_seal = seal_suite(development, output_dir / "development-cases.json")
    holdout_seal = seal_suite(holdout, output_dir / "holdout-cases.json")
    contamination = contamination_check(development, holdout)
    leakage = leakage_attack_battery(registry, holdout)

    evaluations: dict[str, Any] = {}
    for name in COURT_CANDIDATES:
        evaluations[name] = {
            "development": evaluate_candidate_on_suite(name, development, registry),
            "holdout": evaluate_candidate_on_suite(name, holdout, registry),
        }

    baseline_holdout = evaluations[BASELINE_CANDIDATE]["holdout"]
    decisions = []
    for name, evaluation in evaluations.items():
        if name == BASELINE_CANDIDATE:
            continue
        decisions.append(promotion_decision(
            evaluation["holdout"], baseline_holdout,
            leakage=leakage, contamination=contamination,
        ))

    def _strip_latency(evaluation: dict[str, Any]) -> dict[str, Any]:
        return {
            "candidate": evaluation["candidate"],
            "suite": evaluation["suite"],
            "scored_count": evaluation["scored_count"],
            "abstentions_standard": evaluation["abstentions_standard"],
            "abstentions_probe": evaluation["abstentions_probe"],
            "metrics": evaluation["metrics"],
        }

    id_basis = {
        "spec": COURT_SPEC,
        "development_sha256": dev_seal["cases_sha256"],
        "holdout_sha256": holdout_seal["cases_sha256"],
        "registry_manifest_sha256": registry["manifest_sha256"],
        "contamination": contamination,
        "leakage": leakage,
        "evaluations": {name: {suite: _strip_latency(ev) for suite, ev in evs.items()}
                        for name, evs in evaluations.items()},
        "decisions": decisions,
    }
    receipt = {
        **id_basis,
        "court_receipt_id": f"pcourt-{sha256_hex(canonical_bytes(id_basis))[:12]}",
        "baseline_candidate": BASELINE_CANDIDATE,
        "latency_ms_mean": {name: evs["holdout"]["latency_ms_mean"] for name, evs in evaluations.items()},
        "latency_budget_ms": LATENCY_BUDGET_MS,
        "proofs": {
            "beneficial_candidate_promoted": any(d["status"] == "promote" for d in decisions),
            # "Attractive" is itself proven: the rejected candidate must have
            # IMPROVED development-suite proper scoring over the baseline.
            "attractive_regression_rejected": any(
                d["status"] == "reject" and d["candidate"] == "seq_prefix_overfit"
                and evaluations["seq_prefix_overfit"]["development"]["metrics"]["nll"]
                    < evaluations[BASELINE_CANDIDATE]["development"]["metrics"]["nll"]
                for d in decisions),
        },
        "external_execution": False,
        "development_seal": dev_seal,
        "holdout_seal": holdout_seal,
    }
    (output_dir / "prediction-court-receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True))
    detail = {
        name: {suite: ev["per_case"] for suite, ev in evs.items()}
        for name, evs in evaluations.items()
    }
    (output_dir / "prediction-court-per-case.json").write_text(
        json.dumps(detail, indent=2, sort_keys=True))
    return receipt
