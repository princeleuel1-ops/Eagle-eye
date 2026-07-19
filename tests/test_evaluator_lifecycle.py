"""V4 blocker 1: evaluator secret custody + irreversible lifecycle.

Required negative test (audit): attempt to reveal before finalization ->
hard failure; confirm the promotion/final suites cannot be reconstructed
early (the secret is unreachable and the commitment alone is one-way).
"""
from pathlib import Path

import pytest

from eagle_eye.evolution import EvolutionController, default_config, predictor_from_config
from eagle_eye.posterior_engine import build_demo_registry
from eagle_eye.sealed_evaluator import (
    EVALUATOR_VERSION,
    EvaluatorError,
    SealedEvaluator,
    commitment_for,
    provision_evaluator_secret,
)

ROOT = Path(__file__).resolve().parents[1]


def _evaluator(secret="lifecycle-secret", **kw):
    return SealedEvaluator(tenant_id="tenant-demo", run_id="r-lc", secret=secret, **kw)


def test_reveal_before_finalize_hard_fails_in_initialized():
    evaluator = _evaluator()
    assert evaluator.lifecycle == "INITIALIZED"
    with pytest.raises(EvaluatorError, match="reveal refused before FINALIZED"):
        evaluator.reveal_for_replay()


def test_reveal_before_finalize_hard_fails_in_evaluating(registry=None):
    registry = registry or build_demo_registry()
    evaluator = _evaluator("lc-2")
    controller = EvolutionController(registry, evaluator, run_seed=7,
                                     run_context={"code_revision": "t", "dependency_lock_sha256": "t"})
    controller._champ_dev_cache = 99.0
    controller.decide(controller.propose_candidates(1)[0])  # spends a real look
    assert evaluator.lifecycle == "EVALUATING"
    with pytest.raises(EvaluatorError, match="reveal refused before FINALIZED"):
        evaluator.reveal_for_replay()
    # after finalize, reveal works and the lifecycle is REVEALABLE
    evaluator.finalize()
    reveal = evaluator.reveal_for_replay()
    assert reveal["lifecycle_at_reveal"] == "REVEALABLE"
    assert evaluator.lifecycle == "REVEALABLE"


def test_no_looks_after_finalize_and_finalize_is_irreversible():
    registry = build_demo_registry()
    evaluator = _evaluator("lc-3")
    row = evaluator.finalize()
    assert row["body"]["event"] == "FINALIZED"  # lifecycle row is in the signed ledger
    with pytest.raises(EvaluatorError, match="already finalized"):
        evaluator.finalize()
    with pytest.raises(EvaluatorError, match="no further looks"):
        evaluator.compare(champion_config=default_config(), challenger_config=default_config(),
                          candidate_id="c", snapshot_id="s", registry=registry,
                          fn_factory=predictor_from_config, nonce="post-final")
    with pytest.raises(EvaluatorError, match="no further looks"):
        evaluator.final_audit(config=default_config(), champion_id="c", registry=registry,
                              fn_factory=predictor_from_config, nonce="post-final-2")


def test_secret_and_suites_not_reachable_before_reveal():
    evaluator = _evaluator("lc-4")
    for private in ("__promotion", "__final", "__secret", "__private", "__secret_provenance"):
        assert not hasattr(evaluator, private.lstrip("_"))
        with pytest.raises(AttributeError):
            getattr(evaluator, private)
    # only hashes are public before reveal: commitments carry no rows/labels
    assert set(evaluator.suite_commitments["promotion"]) == {
        "case_count", "world_seed", "scale", "cases_sha256", "truth_sha256"}


def test_provisioned_secrets_are_random_and_committed_with_provenance():
    a, b = provision_evaluator_secret(), provision_evaluator_secret()
    assert a["secret"] != b["secret"]  # CSPRNG: two mints never collide
    assert len(a["secret"]) == 64 and set(a["secret"]) <= set("0123456789abcdef")
    assert a["provenance"] == "csprng_operator_boundary"
    # the commitment binds provenance: same secret, different provenance -> different commitment
    assert commitment_for("s", "csprng_operator_boundary") != commitment_for("s", "test_fixture")
    with pytest.raises(EvaluatorError, match="unknown secret provenance"):
        SealedEvaluator(tenant_id="t", run_id="r", secret="s", secret_provenance="made_up")


def test_derived_secret_pattern_is_abolished_in_run_script():
    """Regression grep for the V3 defect: the benchmark must never derive the
    evaluator secret from public seeds / code revisions again."""
    source = (ROOT / "scripts" / "run_sealed_evolution.py").read_text()
    assert "evaluator-secret-" not in source
    assert "provision_evaluator_secret" in source
    # the default path must be the CSPRNG boundary (secret arg defaults to None)
    import inspect
    import importlib.util
    spec = importlib.util.spec_from_file_location("rse_check", ROOT / "scripts" / "run_sealed_evolution.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert inspect.signature(module.main).parameters["evaluator_secret"].default is None


def test_single_evaluator_version_constant():
    """V4 blocker 4: one imported constant everywhere; no 2.0/2.1 mismatch."""
    assert EVALUATOR_VERSION == "sealed-evaluator/4.0"
    for rel in ("scripts/run_sealed_evolution.py", "src/eagle_eye/evolution.py",
                "scripts/replay_sealed_evolution.py"):
        source = (ROOT / rel).read_text()
        assert "sealed-evaluator/2.0" not in source and "sealed-evaluator/2.1" not in source
        assert "EVALUATOR_VERSION" in source
