import copy

import pytest

from eagle_eye.evolution import (
    CHALLENGER_BUDGET_PER_CYCLE,
    EvolutionController,
    MUTATION_WHITELIST,
    PROMOTION_STATES,
    default_config,
    validate_mutation,
)
from eagle_eye.posterior_engine import build_demo_registry
from eagle_eye.prior_registry import build_registry
from eagle_eye.sealed_evaluator import SealedEvaluator


@pytest.fixture(scope="module")
def registry():
    return build_demo_registry()


def _controller(registry, secret="s1", seed=777):
    evaluator = SealedEvaluator(tenant_id="tenant-demo", run_id="run-t", secret=secret)
    return EvolutionController(registry, evaluator, run_seed=seed,
                               run_context={"code_revision": "test", "dependency_lock_sha256": "test"})


@pytest.fixture(scope="module")
def controller(registry):
    return _controller(registry)


def test_whitelist_rejects_untyped_mutations():
    with pytest.raises(ValueError, match="outside whitelist"):
        validate_mutation({"predictor.source_code": "os.system('x')"})
    with pytest.raises(ValueError, match="outside allowed grid"):
        validate_mutation({"selector.k_max": 500})
    validate_mutation({"selector.k_max": 12})


def test_candidate_generation_deterministic_and_snapshot_bound(registry):
    a = _controller(registry).propose_candidates(1)
    b = _controller(registry).propose_candidates(1)
    assert [c["candidate_id"] for c in a] == [c["candidate_id"] for c in b]
    assert len(a) <= CHALLENGER_BUDGET_PER_CYCLE
    # candidate-ID collision across registries is impossible: same diff on a
    # mutated registry yields a different snapshot-bound id (audit blocker B)
    controller = _controller(registry)
    ids_before = {c["candidate_id"] for c in controller.propose_candidates(1)}
    grown = build_registry(list(registry["tasks"])[:-1], release="prior-registry/shrunk")
    controller.update_registry(grown)
    ids_after = {c["candidate_id"] for c in controller.propose_candidates(1)}
    assert ids_before.isdisjoint(ids_after)


def test_snapshot_recomputed_on_registry_mutation(registry, controller):
    snap_before = controller.snapshot_id
    grown = build_registry(list(registry["tasks"])[:-2], release="prior-registry/shrunk2")
    fresh = _controller(registry)
    fresh.update_registry(grown)
    assert fresh.snapshot_id != snap_before


def test_stale_snapshot_candidate_is_blocked(registry):
    controller = _controller(registry, secret="s2")
    candidate = controller.propose_candidates(1)[0]
    grown = build_registry(list(registry["tasks"])[:-1], release="prior-registry/shrunk3")
    controller.update_registry(grown)  # registry mutates AFTER candidate creation
    decision = controller.decide(candidate)
    assert decision["state"] == "BLOCKED_CONTAMINATION"
    assert any("stale_snapshot" in r for r in decision["reasons"])


def test_evaluator_boundary_hides_truth_and_seeds(registry):
    evaluator = SealedEvaluator(tenant_id="tenant-demo", run_id="r", secret="s3")
    for private in ("__promotion", "__final", "__secret", "__private"):
        assert not hasattr(evaluator, private.lstrip("_"))
        with pytest.raises(AttributeError):
            getattr(evaluator, private)
    assert len(evaluator.seed_commitment) == 64  # commitment published, secret not


def test_replay_protection_and_charged_champion(registry):
    controller = _controller(registry, secret="s4")
    evaluator = controller.evaluator
    config = default_config()
    challenger = {**config, "selector.k_max": 12}
    from eagle_eye.evolution import predictor_from_config
    response = evaluator.compare(champion_config=config, challenger_config=challenger,
                                 candidate_id="cand-x", snapshot_id=controller.snapshot_id,
                                 registry=registry, fn_factory=predictor_from_config, nonce="n-1")
    assert evaluator.looks_spent() == 1  # champion + challenger inside ONE charged look
    assert response["body"]["champion_aggregates"]["metrics"]["nll"] is not None
    with pytest.raises(Exception, match="replayed nonce"):
        evaluator.compare(champion_config=config, challenger_config=challenger,
                          candidate_id="cand-x", snapshot_id=controller.snapshot_id,
                          registry=registry, fn_factory=predictor_from_config, nonce="n-1")
    stats = response["body"]["statistics"]
    for field in ("hypothesis", "t_statistic_micro", "ci_upper_micro", "alpha_per_look_micro",
                  "alpha_spent_after_micro", "stopping_rule", "decision_threshold",
                  "n_paired", "assumptions", "failure_conditions"):
        assert field in stats, field


def test_final_audit_is_one_shot(registry):
    controller = _controller(registry, secret="s5")
    from eagle_eye.evolution import predictor_from_config
    controller.evaluator.final_audit(config=default_config(), champion_id="c", registry=registry,
                                     fn_factory=predictor_from_config, nonce="fa-1")
    with pytest.raises(Exception, match="one-shot"):
        controller.evaluator.final_audit(config=default_config(), champion_id="c", registry=registry,
                                         fn_factory=predictor_from_config, nonce="fa-2")


class _StubEvaluator:
    """Unit stub for gate-branch tests: returns crafted aggregate responses so
    each rejection gate can be exercised deterministically on a dev-attractive
    challenger. The stub mimics the signed-row shape; gate logic is real."""

    seed_commitment = "0" * 64
    alpha_total, max_looks, alpha_per_look = 0.05, 20, 0.0025

    def __init__(self, body):
        self._body = body
        from eagle_eye.signed_chain import SignedChain
        from eagle_eye.signing import generate_demo_keypair
        pk, pub = generate_demo_keypair()
        self.ledger = SignedChain(tenant_id="tenant-demo", run_id="r", chain_id="evaluator-access",
                                  private_key=pk, public_key=pub)

    def looks_spent(self):
        return 0

    def alpha_spent(self):
        return 0.0

    def compare(self, **kwargs):
        return self.ledger.append(self._body)


def _gate_case(registry, body):
    controller = _controller(registry, secret="s6")
    controller.evaluator = _StubEvaluator(body)
    controller._champ_dev_cache = 99.0  # any challenger is dev-attractive
    candidate = controller.propose_candidates(1)[0]
    return controller.decide(candidate)


def _body(**overrides):
    metrics = {"nll": 700000, "crps": 300000, "coverage80": 850000, "nll_temporal_ood": 400000,
               "permutation_spread_max": 0}
    body = {"kind": "promotion_look_result", "look_index": 1,
            "charge_row_hash": "c" * 64, "terminal_status": "SUCCEEDED",
            "statistics": {"significant_improvement": True, "ci_upper_micro": -1000,
                            "n_paired": 40},
            "challenger_aggregates": {"metrics": dict(metrics), "scored_count": 40,
                                        "abstentions_standard": 0, "abstentions_probe": 2,
                                        "probe_count": 2},
            "champion_aggregates": {"metrics": {"nll": 750000, "coverage80": 850000,
                                                  "nll_temporal_ood": 450000}, "scored_count": 40}}
    for path, value in overrides.items():
        parts = path.split(".")
        node = body
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    return body


def test_trust_gate_rejects_dev_attractive_challenger(registry):
    decision = _gate_case(registry, _body(**{"challenger_aggregates.abstentions_standard": 3}))
    assert decision["state"] == "BLOCKED_TRUST_REGRESSION"
    decision = _gate_case(registry, _body(**{"challenger_aggregates.metrics": {
        "nll": 700000, "crps": 300000, "coverage80": 850000, "nll_temporal_ood": 400000,
        "permutation_spread_max": 400000}}))
    assert decision["state"] == "BLOCKED_TRUST_REGRESSION"


def test_calibration_gate_rejects_dev_attractive_challenger(registry):
    decision = _gate_case(registry, _body(**{"challenger_aggregates.metrics": {
        "nll": 700000, "crps": 300000, "coverage80": 600000, "nll_temporal_ood": 400000,
        "permutation_spread_max": 0}}))
    assert decision["state"] == "BLOCKED_CALIBRATION_REGRESSION"


def test_shift_gate_rejects_dev_attractive_challenger(registry):
    decision = _gate_case(registry, _body(**{"challenger_aggregates.metrics": {
        "nll": 700000, "crps": 300000, "coverage80": 850000, "nll_temporal_ood": 600000,
        "permutation_spread_max": 0}}))
    assert decision["state"] == "BLOCKED_SHIFT"


def test_insignificant_sealed_test_rejects(registry):
    decision = _gate_case(registry, _body(**{"statistics.significant_improvement": False}))
    assert decision["state"] == "REJECTED"
    assert "sealed_paired_test_not_significant" in decision["reasons"][0]


def test_lineage_is_signed_and_states_valid(registry):
    controller = _controller(registry, secret="s7")
    candidate = controller.propose_candidates(1)[0]
    decision = controller.decide(candidate)
    assert decision["state"] in PROMOTION_STATES
    row = controller.lineage_chain.rows[-1]
    assert row["signature_b64"] and row["signer_key_id"].startswith("ed25519:")
    anchor = controller.lineage_chain.anchor()
    from eagle_eye.signed_chain import verify_chain
    registry_signers = {"trusted_signers": [{
        "key_id": controller.lineage_chain.signer_key_id,
        "public_key_pem": controller.lineage_chain.public_key.decode()}]}
    assert verify_chain(controller.lineage_chain.rows, anchor, registry_signers,
                        expected_tenant="tenant-demo")["verified"] is True


def test_candidate_exploration_stable_under_run_context_changes(registry):
    """Regression (V4): a documentation-only code edit (run_context change)
    must NOT reshuffle which mutations get explored. The candidate DIFF
    sequence is stable across run_contexts; candidate IDS still differ
    because they embed the full snapshot (contamination binding intact)."""
    e1 = SealedEvaluator(tenant_id="tenant-demo", run_id="r", secret="stable-x")
    e2 = SealedEvaluator(tenant_id="tenant-demo", run_id="r", secret="stable-x")
    c1 = EvolutionController(registry, e1, run_seed=777,
                             run_context={"code_revision": "aaaa", "dependency_lock_sha256": "x"})
    c2 = EvolutionController(registry, e2, run_seed=777,
                             run_context={"code_revision": "bbbb", "dependency_lock_sha256": "y"})
    a, b = c1.propose_candidates(1), c2.propose_candidates(1)
    assert [x["diff"] for x in a] == [x["diff"] for x in b]
    assert c1.snapshot_id != c2.snapshot_id  # binding still context-sensitive
    assert [x["candidate_id"] for x in a] != [x["candidate_id"] for x in b]
