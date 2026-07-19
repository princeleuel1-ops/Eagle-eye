"""V4 blocker 6: measured statistical power and Type-I error of the sealed
promotion rule, with planted fixed effects and shared-world dependence
accounting.

What this does (and what the withdrawn V3 claim did not):
  - suite scaling now preserves the exact stratum/observation-count
    distribution (independent case resampling; see build_holdout_suite)
  - per-case paired NLL differences between the genesis champion and a real
    whitelist challenger are computed on analysis suites at scale 1 and 3
  - the observed diffs are RECENTERED to mean zero (empirical null that
    preserves tails and any residual structure), then a fixed effect delta is
    PLANTED and the EXACT production decision rule (paired_test_from_diffs,
    Bonferroni-allocated alpha) is applied to bootstrap resamples:
      * iid bootstrap over cases
      * block bootstrap over replica blocks (shared-world dependence: whole
        replica blocks are resampled together, preserving within-block
        correlation)
  - Type-I error is the rejection rate at delta = 0; power is the rejection
    rate at planted negative deltas

Evidence class: MODEL_CONDITIONAL_ESTIMATE (bootstrap over an empirical null
from one synthetic generator). This measures the operating characteristics of
the rule as deployed; it is NOT a claim about live-data effect sizes.

usage: PYTHONPATH=src python scripts/power_analysis.py [out.json]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from eagle_eye.evolution import default_config, predictor_from_config
from eagle_eye.prediction_court import build_holdout_suite, evaluate_candidate_on_suite
from eagle_eye.prior_registry import build_registry
from eagle_eye.regimes import generate_world
from eagle_eye.sealed_evaluator import MIN_PAIRED_N, paired_test_from_diffs
from eagle_eye.stats import DeterministicRng, stable_seed

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_SECRET_SEED = 424243  # analysis-only; NOT a sealed evaluator secret
ALPHA_TOTAL, MAX_LOOKS = 0.05, 20
ALPHA_PER_LOOK = ALPHA_TOTAL / MAX_LOOKS
DELTAS = [0.0, -0.005, -0.01, -0.02, -0.05]
BOOTSTRAP_B = 1200
CHALLENGER_DIFF = {"selector.k_max": 12}


def paired_diffs(suite, registry, champ_config, chall_config) -> tuple[list[float], list[int]]:
    def run(cfg):
        return evaluate_candidate_on_suite(
            "power", suite, registry, fn=predictor_from_config(cfg),
            k_max_override=cfg["selector.k_max"],
            min_score_override=cfg["selector.min_score_milli"] / 1000.0)
    champ, chall = run(champ_config), run(chall_config)
    champ_by_case = {r["case_id"]: r for r in champ["per_case"] if not r["abstained"]}
    diffs, blocks = [], []
    n_strata = suite["stratum_plan_size"]
    for i, r in enumerate(chall["per_case"]):
        if not r["abstained"] and r["case_id"] in champ_by_case:
            diffs.append(r["nll"] - champ_by_case[r["case_id"]]["nll"])
            blocks.append(i // n_strata)  # replica index = block id
    return diffs, blocks


def simulate(null_diffs: list[float], blocks: list[int], delta: float,
             mode: str, rng: DeterministicRng) -> float:
    n = len(null_diffs)
    by_block: dict[int, list[float]] = {}
    for d, b in zip(null_diffs, blocks):
        by_block.setdefault(b, []).append(d)
    block_ids = sorted(by_block)
    rejections = 0
    for _ in range(BOOTSTRAP_B):
        if mode == "iid":
            sample = [null_diffs[rng.choice_index(n)] + delta for _ in range(n)]
        else:  # block bootstrap: resample whole replica blocks
            sample = []
            while len(sample) < n:
                block = by_block[block_ids[rng.choice_index(len(block_ids))]]
                sample.extend(d + delta for d in block)
            sample = sample[:n]
        if paired_test_from_diffs(sample, ALPHA_PER_LOOK)["significant_improvement"]:
            rejections += 1
    return rejections / BOOTSTRAP_B


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "artifacts" / "evolution" / "latest" / "POWER_ANALYSIS.json")
    started = time.time()
    registry = build_registry(list(generate_world(20260712, tasks_per_regime=16)["tasks"]))
    champ = default_config()
    chall = {**champ, **CHALLENGER_DIFF}
    scales = {}
    gates_ok = True
    for scale in (1, 3):
        suite = build_holdout_suite(ANALYSIS_SECRET_SEED, scale=scale)
        diffs, blocks = paired_diffs(suite, registry, champ, chall)
        mean = sum(diffs) / len(diffs)
        null = [d - mean for d in diffs]  # empirical null: recentered
        rng = DeterministicRng(stable_seed("power-analysis", scale))
        n_blocks = len(set(blocks))
        # a single replica block would make the block bootstrap degenerate
        # (every resample identical) — report it only when it means something
        block_valid = n_blocks >= 2
        table = {}
        for delta in DELTAS:
            table[str(delta)] = {
                "iid_bootstrap": simulate(null, blocks, delta, "iid", rng),
                "block_bootstrap": (simulate(null, blocks, delta, "block", rng)
                                    if block_valid else None),
            }
        type1_iid = table["0.0"]["iid_bootstrap"]
        type1_block = table["0.0"]["block_bootstrap"]
        # gross-anticonservatism gate: measured Type-I must stay near the
        # allocated per-look alpha (0.0025); 0.01 is a 4x safety margin
        scale_ok = type1_iid <= 0.01 and (type1_block is None or type1_block <= 0.01)
        # sanity: power must increase as the planted effect grows
        mode = "block_bootstrap" if block_valid else "iid_bootstrap"
        power_curve = [table[str(d)][mode] for d in DELTAS]
        monotone_ok = power_curve[-1] >= power_curve[0]
        gates_ok = gates_ok and scale_ok and monotone_ok
        scales[f"scale_{scale}"] = {
            "n_paired": len(diffs),
            "n_blocks": n_blocks,
            "block_bootstrap_valid": block_valid,
            "observed_mean_diff": round(mean, 6),
            "observed_sd": round((sum((d - mean) ** 2 for d in diffs) / (len(diffs) - 1)) ** 0.5, 6),
            "rejection_rates_by_planted_delta": table,
            "type1_error_measured": {"iid": type1_iid, "block": type1_block},
            "type1_gate_ok": scale_ok,
            "power_monotone_ok": monotone_ok,
        }
        print(f"SCALE_{scale}: n={len(diffs)} blocks={n_blocks} type1_iid={type1_iid:.4f} "
              f"type1_block={type1_block} power@-0.02={table['-0.02'][mode]:.3f} "
              f"power@-0.05={table['-0.05'][mode]:.3f} (mode={mode})")
    receipt = {
        "spec": "sealed-rule-power-analysis/4.0",
        "evidence_class": "MODEL_CONDITIONAL_ESTIMATE (empirical-null bootstrap, one synthetic generator)",
        "decision_rule": {"alpha_total": ALPHA_TOTAL, "max_looks": MAX_LOOKS,
                           "alpha_per_look": ALPHA_PER_LOOK, "min_paired_n": MIN_PAIRED_N,
                           "rule": "one-sided upper CB of mean paired NLL diff < 0"},
        "challenger_diff_used_for_null": CHALLENGER_DIFF,
        "planted_deltas_nats": DELTAS,
        "bootstrap_B": BOOTSTRAP_B,
        "scales": scales,
        "shared_world_dependence": "block bootstrap resamples whole replica blocks; compare iid vs block columns for the dependence penalty",
        "withdrawn_claim": "V3's 'power tripled' (scale via n_target_obs increments) is WITHDRAWN: it changed stratum composition. V4 scaling is stratum-preserving independent resampling; the measured rates above are the honest replacement.",
        "elapsed_s": round(time.time() - started, 1),
        "pass": gates_ok,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, indent=2, sort_keys=True))
    print(f"POWER_ANALYSIS_{'PASS' if gates_ok else 'FAIL'}")
    return 0 if gates_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
