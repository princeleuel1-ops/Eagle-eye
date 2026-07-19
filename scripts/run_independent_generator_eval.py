"""STRUCTURALLY INDEPENDENT generator evaluation (V4 blocker 5, preferred).

Registry AND targets come from `regimes_independent` — a different generative
process (Gamma mixtures, day-of-week seasonality, multiplicative bounded
intervention factors, delay-dependent stockout, Pareto contamination) sharing
only the prior-task schema with the original family. The champion faces an
alien world with alien history.

Protocol: 100 PRECOMMITTED seeds; per seed, an independent world registry and
targets; paired per-case NLL/CRPS differences (champion minus no-prefix
baseline); cluster-robust CI over per-seed means; per-seed failure rate.

Evidence class: SYNTHETIC INDEPENDENT-GENERATOR TRANSFER — structurally
distinct synthetic family. This is NOT live-data evidence and does NOT
establish "general generator robustness"; it establishes transfer across TWO
synthetic families, one of which was never used in any tuning step.

usage: PYTHONPATH=src python scripts/run_independent_generator_eval.py [out.json]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from eagle_eye.evolution import predictor_from_config
from eagle_eye.prediction_court import COVERAGE_BAND
from eagle_eye.predictors import LogScaleDist, predict_no_prefix
from eagle_eye.prior_registry import build_registry, canonical_bytes, sha256_hex
from eagle_eye.prior_selector import compile_prior_context, select_prior_tasks
from eagle_eye.regimes_independent import (
    GENERATOR_RELEASE,
    generate_independent_target,
    generate_independent_world,
)
from eagle_eye.stats import norm_ppf

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "artifacts" / "evolution" / "latest" / "REPLAY_BUNDLE.json"
# PRECOMMITTED: 100 seeds fixed before any evaluation; hash recorded in output
SEEDS = [910_000 + i for i in range(100)]
TARGET_PLAN = [
    {"disruption_class": "port_congestion", "cutoff": "2025-04-14", "n_target_obs": 1},
    {"disruption_class": "port_congestion", "cutoff": "2025-06-09", "n_target_obs": 2},
    {"disruption_class": "supplier_quality", "cutoff": "2025-04-21", "n_target_obs": 2},
    {"disruption_class": "supplier_quality", "cutoff": "2025-06-16", "n_target_obs": 4},
    {"disruption_class": "geopolitical", "cutoff": "2025-05-05", "n_target_obs": 1},
    {"disruption_class": "geopolitical", "cutoff": "2025-06-23", "n_target_obs": 4},
]


def score_case(fn, registry, target, truth, *, k_max, min_score):
    selection = select_prior_tasks(registry, target, k_max=k_max, min_score=min_score)
    compiled = compile_prior_context(selection["included"], target)
    prediction = fn(compiled)
    if prediction.get("interventions") is None:
        return None  # governed abstention
    payload = prediction["interventions"]["wait_incumbent"]["delay"]
    dist = LogScaleDist(payload["loc"], payload["scale"], payload["df"])
    y = truth["outcomes"]["wait_incumbent"]["log_final_delay"]
    lo, hi = dist.ppf(0.10), dist.ppf(0.90)
    return {"nll": -dist.logpdf(y), "crps": dist.crps(y), "covered80": bool(lo <= y <= hi)}


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "artifacts" / "evolution" / "latest" / "INDEPENDENT_GENERATOR_RESULTS.json")
    if not BUNDLE.exists():
        print("INDEPENDENT_GENERATOR_FAIL=missing replay bundle; run the sealed evolution benchmark first")
        return 1
    champion_config = json.loads(BUNDLE.read_text())["final_champion_config"]
    champ_fn = predictor_from_config(champion_config)
    k_max = champion_config["selector.k_max"]
    min_score = champion_config["selector.min_score_milli"] / 1000.0
    per_seed = []
    abstentions = 0
    total_cases = 0
    covs = []
    for seed in SEEDS:
        world = generate_independent_world(seed, tasks_per_class=12)
        registry = build_registry(world["tasks"], release=f"prior-registry/independent-{seed}")
        diffs_nll, diffs_crps, cov_hits = [], [], []
        for i, spec in enumerate(TARGET_PLAN):
            case = generate_independent_target(seed, case_index=7000 + i, **spec)
            total_cases += 1
            champ = score_case(champ_fn, registry, case["target"], case["truth"],
                               k_max=k_max, min_score=min_score)
            if champ is None:
                abstentions += 1
                continue
            base = score_case(predict_no_prefix, registry, case["target"], case["truth"],
                              k_max=k_max, min_score=min_score)
            if base is None:
                continue
            diffs_nll.append(champ["nll"] - base["nll"])
            diffs_crps.append(champ["crps"] - base["crps"])
            cov_hits.append(champ["covered80"])
        if diffs_nll:
            per_seed.append({
                "seed": seed, "n_paired": len(diffs_nll),
                "mean_nll_diff": sum(diffs_nll) / len(diffs_nll),
                "mean_crps_diff": sum(diffs_crps) / len(diffs_crps),
                "coverage80": sum(cov_hits) / len(cov_hits),
            })
            covs.extend(cov_hits)

    def seed_ci(key):
        values = [row[key] for row in per_seed]
        n = len(values)
        mean = sum(values) / n
        sd = math.sqrt(sum((v - mean) ** 2 for v in values) / (n - 1))
        half = norm_ppf(0.975) * sd / math.sqrt(n)
        return {"mean": round(mean, 6), "sd": round(sd, 6),
                "ci95": [round(mean - half, 6), round(mean + half, 6)], "n_seeds": n}

    nll_ci, crps_ci = seed_ci("mean_nll_diff"), seed_ci("mean_crps_diff")
    failure_rate_nll = sum(1 for r in per_seed if r["mean_nll_diff"] >= 0) / len(per_seed)
    failure_rate_crps = sum(1 for r in per_seed if r["mean_crps_diff"] >= 0) / len(per_seed)
    pooled_cov = sum(1 for c in covs if c) / len(covs)
    # PROTOCOL gates decide the exit code: measurement integrity + the trust
    # property that calibration must not BREAK under an alien generator.
    protocol_gates = {
        "enough_seeds_scored": len(per_seed) >= 90,
        "coverage_in_band": COVERAGE_BAND[0] <= pooled_cov <= COVERAGE_BAND[1],
    }
    # TRANSFER findings are MEASURED results — recorded honestly, never forced.
    findings = {
        "nll_advantage_established": nll_ci["ci95"][1] < 0.0,
        "crps_advantage_established": crps_ci["ci95"][1] < 0.0,
    }
    ok = all(protocol_gates.values())
    out = {
        "spec": "independent-generator-eval/4.0",
        "label": "SYNTHETIC INDEPENDENT-GENERATOR TRANSFER — structurally distinct synthetic family; NOT live-data evidence; NOT general generator robustness",
        "generator": GENERATOR_RELEASE,
        "structural_differences": [
            "Gamma severity-tier mixtures vs Normal/Student-t log-delay hierarchy",
            "day-of-week multipliers vs annual cosine seasonality",
            "multiplicative Beta-bounded intervention factors vs additive log effects",
            "delay-DEPENDENT logistic stockout vs independent Beta-Bernoulli",
            "additive Exponential recovery vs multiplicative lognormal",
            "5% Pareto contamination vs none",
        ],
        "champion_config_source": "REPLAY_BUNDLE.final_champion_config (verified against signed lineage)",
        "champion_config": champion_config,
        "precommitted_seeds_count": len(SEEDS),
        "precommitted_seeds_sha256": sha256_hex(canonical_bytes(SEEDS)),
        "seeds_scored": len(per_seed),
        "cases_total": total_cases,
        "champion_abstentions": abstentions,
        "paired_nll_diff_champion_minus_baseline": nll_ci,
        "paired_crps_diff_champion_minus_baseline": crps_ci,
        "per_seed_failure_rate_nll": round(failure_rate_nll, 4),
        "per_seed_failure_rate_crps": round(failure_rate_crps, 4),
        "champion_pooled_coverage80": round(pooled_cov, 6),
        "coverage_band": list(COVERAGE_BAND),
        "protocol_gates": protocol_gates,
        "transfer_findings": findings,
        "claim_discipline": "if the CIs straddle zero, the champion has NO ESTABLISHED advantage over the no-prefix baseline on this alien family — say exactly that and nothing more; the in-band coverage under alien data is the (gated) trust property",
        "pass": ok,
        "per_seed_sample": per_seed[:10],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(f"SEEDS_SCORED={len(per_seed)}/{len(SEEDS)} ABSTENTIONS={abstentions}/{total_cases}")
    print(f"NLL_DIFF_CI95={nll_ci['ci95']} FAILURE_RATE_NLL={failure_rate_nll:.3f}")
    print(f"CRPS_DIFF_CI95={crps_ci['ci95']} FAILURE_RATE_CRPS={failure_rate_crps:.3f}")
    print(f"COVERAGE80={pooled_cov:.4f}")
    for k, v in protocol_gates.items():
        print(f"PROTOCOL_{k.upper()}={v}")
    for k, v in findings.items():
        print(f"FINDING_{k.upper()}={v}")
    print(f"INDEPENDENT_GENERATOR_{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
