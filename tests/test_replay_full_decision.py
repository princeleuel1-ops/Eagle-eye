"""Non-vacuous full-decision replay: a REAL sealed look is spent, then the
recorded statistics are recomputed from the revealed secret in a fresh
evaluator context and must match bit-for-bit (micro units)."""
from eagle_eye.evolution import EvolutionController, default_config, predictor_from_config
from eagle_eye.posterior_engine import build_demo_registry
from eagle_eye.prediction_court import build_holdout_suite, evaluate_candidate_on_suite
from eagle_eye.sealed_evaluator import SealedEvaluator, paired_comparison
from eagle_eye.stats import stable_seed


def test_spent_look_is_fully_recomputable_from_reveal():
    registry = build_demo_registry()
    secret = "replay-proof-secret"
    evaluator = SealedEvaluator(tenant_id="tenant-demo", run_id="r", secret=secret, suite_scale=1)
    controller = EvolutionController(registry, evaluator, run_seed=101,
                                     run_context={"code_revision": "t", "dependency_lock_sha256": "t"})
    controller._champ_dev_cache = 99.0  # force the challenger past the dev pre-screen
    candidate = controller.propose_candidates(1)[0]
    decision = controller.decide(candidate)
    assert decision["evaluator_response_hash"] is not None  # a real look was spent
    recorded = next(r for r in evaluator.ledger.rows
                    if r["row_hash"] == decision["evaluator_response_hash"])["body"]["statistics"]
    # V4 lifecycle: the reveal is ONLY possible after irreversible finalize —
    # the sealed suite cannot be rebuilt while looks remain possible.
    evaluator.finalize()
    reveal = evaluator.reveal_for_replay()
    suite = build_holdout_suite(stable_seed("promotion-holdout", reveal["evaluator_secret"]) % (1 << 31),
                                scale=evaluator.suite_scale)

    def run(config):
        return evaluate_candidate_on_suite("replay", suite, registry,
                                           fn=predictor_from_config(config),
                                           k_max_override=config["selector.k_max"],
                                           min_score_override=config["selector.min_score_milli"] / 1000.0)

    stats = paired_comparison(run(default_config()), run(candidate["config"]), 0.05 / 20.0)
    for key in ("n_paired", "mean_diff_micro", "sd_micro", "t_statistic_micro",
                "ci_lower_micro", "ci_upper_micro", "significant_improvement"):
        assert stats[key] == recorded[key], key
