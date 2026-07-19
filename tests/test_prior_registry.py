import copy

import pytest

from eagle_eye.prior_registry import (
    RegistryError,
    build_registry,
    tasks_visible_at,
    validate_task,
    verify_registry,
)
from eagle_eye.prior_selector import CompilerError, compile_prior_context, select_prior_tasks
from eagle_eye.regimes import default_world_config, generate_target_case, generate_world


@pytest.fixture(scope="module")
def world():
    return generate_world(20260712, tasks_per_regime=12)


@pytest.fixture(scope="module")
def registry(world):
    return build_registry(world["tasks"])


@pytest.fixture(scope="module")
def target_case(world):
    return generate_target_case(
        world, case_index=1, tenant_id="tenant-demo",
        disruption_class="port_congestion", cutoff="2025-03-15", n_target_obs=3,
    )


def test_world_is_deterministic():
    a = generate_world(77, tasks_per_regime=3)
    b = generate_world(77, tasks_per_regime=3)
    assert a["tasks"] == b["tasks"]
    c = generate_world(78, tasks_per_regime=3)
    assert a["tasks"] != c["tasks"]


def test_generated_tasks_pass_contract_and_truth_is_separate(world):
    for task in world["tasks"]:
        validate_task(task)
        assert "theta" not in task and "regime_id" not in task  # truth never leaks into registry rows
    assert set(world["truth"]["tasks"]) == {t["task_id"] for t in world["tasks"]}


def test_registry_release_is_deterministic_and_verifiable(world, registry):
    again = build_registry(world["tasks"])
    assert registry["manifest_sha256"] == again["manifest_sha256"]
    assert registry["registry_release_id"] == again["registry_release_id"]
    assert verify_registry(registry)


def test_registry_detects_tampering(registry):
    tampered = copy.deepcopy(registry)
    tampered["tasks"][0]["realized"]["log_final_delay"] += 0.5
    assert not verify_registry(tampered)


def test_validate_rejects_observation_after_close(world):
    bad = copy.deepcopy(world["tasks"][0])
    bad["observations"].append({"t": "2030-01-01", "kind": "shipment_delay_signal", "log_delay_days": 1.0})
    with pytest.raises(RegistryError, match="temporal leakage"):
        validate_task(bad)


def test_validate_rejects_open_tasks_and_missing_provenance(world):
    open_task = copy.deepcopy(world["tasks"][0])
    open_task["eligibility"]["status"] = "open"
    with pytest.raises(RegistryError, match="closed"):
        validate_task(open_task)
    no_source = copy.deepcopy(world["tasks"][0])
    no_source["sources"] = []
    with pytest.raises(RegistryError, match="provenance"):
        validate_task(no_source)


def test_duplicate_ids_rejected(world):
    tasks = [world["tasks"][0], copy.deepcopy(world["tasks"][0])]
    with pytest.raises(RegistryError, match="duplicate"):
        build_registry(tasks)


def test_as_of_boundary_excludes_future_and_foreign_tenants(registry):
    cutoff = "2025-03-15"
    result = tasks_visible_at(registry, tenant_id="tenant-demo", as_of_cutoff=cutoff)
    assert result["visible"], "expected at least one visible task"
    for task in result["visible"]:
        assert task["as_of_end"] <= cutoff
        assert task["tenant_id"] == "tenant-demo"
    reasons = {row["reason"] for row in result["exclusion_receipt"]["excluded"]}
    assert "tenant_boundary" in reasons
    assert "not_closed_before_cutoff" in reasons
    total = len(result["visible"]) + len(result["exclusion_receipt"]["excluded"])
    assert total == registry["task_count"]


def test_selector_receipt_is_deterministic_and_leak_free(registry, target_case):
    target = target_case["target"]
    a = select_prior_tasks(registry, target, k_max=8)
    b = select_prior_tasks(registry, target, k_max=8)
    assert a["receipt"]["receipt_sha256"] == b["receipt"]["receipt_sha256"]
    assert a["receipt"]["included_prior_task_ids"] == b["receipt"]["included_prior_task_ids"]
    assert 0 < len(a["included"]) <= 8
    for task in a["included"]:
        assert task["as_of_end"] <= target["as_of_cutoff"]
        assert task["tenant_id"] == target["tenant_id"]
        assert task["disruption_class"] == target["disruption_class"]
    # Receipt accounts for every registry task exactly once.
    assert len(a["receipt"]["decisions"]) == registry["task_count"]


def test_selector_prefers_similar_lanes(registry, target_case):
    result = select_prior_tasks(registry, target_case["target"], k_max=5)
    included_scores = [row["score_milli"] for row in result["receipt"]["decisions"] if row["decision"] == "included"]
    excluded_scored = [row["score_milli"] for row in result["receipt"]["decisions"]
                       if row["decision"] == "excluded" and row["score_milli"] is not None
                       and "k_max_reached" in row["reasons"]]
    if excluded_scored:
        assert min(included_scores) >= max(excluded_scored)


def test_selector_receipt_contains_no_floats(registry, target_case):
    """Receipt hashes are recomputed by BOTH verifier runtimes: floats are
    banned to eliminate Python/Node float-serialization drift (brittle B6)."""
    def assert_no_floats(node, path="receipt"):
        if isinstance(node, bool) or node is None:
            return
        if isinstance(node, float):
            raise AssertionError(f"float at {path}: {node}")
        if isinstance(node, dict):
            for key, value in node.items():
                assert_no_floats(value, f"{path}.{key}")
        elif isinstance(node, list):
            for index, value in enumerate(node):
                assert_no_floats(value, f"{path}[{index}]")

    result = select_prior_tasks(registry, target_case["target"], k_max=5)
    assert_no_floats(result["receipt"])


def test_compiler_preserves_boundaries_and_commits_manifest(registry, target_case):
    target = target_case["target"]
    selection = select_prior_tasks(registry, target, k_max=6)
    compiled = compile_prior_context(selection["included"], target)
    assert compiled["K"] == len(selection["included"])
    assert all(block["boundary"] == "prior" for block in compiled["prior_blocks"])
    assert compiled["target_block"]["boundary"] == "target"
    # Target observations never appear in any prior block payload.
    target_obs = compiled["target_block"]["observations"]
    for block in compiled["prior_blocks"]:
        assert block["observations"] != target_obs or not target_obs
    again = compile_prior_context(selection["included"], target)
    assert compiled["prior_manifest_sha256"] == again["prior_manifest_sha256"]


def test_compiler_refuses_leaky_prior_task(registry, target_case):
    target = target_case["target"]
    selection = select_prior_tasks(registry, target, k_max=4)
    leaky = copy.deepcopy(selection["included"][0])
    leaky["as_of_end"] = "2030-12-31"
    with pytest.raises(CompilerError, match="temporal leakage"):
        compile_prior_context([leaky], target)
    foreign = copy.deepcopy(selection["included"][0])
    foreign["tenant_id"] = "tenant-other"
    with pytest.raises(CompilerError, match="tenant boundary"):
        compile_prior_context([foreign], target)


def test_target_case_truth_holds_all_intervention_outcomes(target_case):
    truth = target_case["truth"]
    assert set(truth["outcomes"]) == {"wait_incumbent", "expedite_shipment", "activate_alternate", "split_order"}
    target = target_case["target"]
    assert "realized" not in target  # outcomes never leak into the predictor-facing target
    assert all(obs["t"] <= target["as_of_cutoff"] for obs in target["observations"])


def test_default_world_config_covers_shifted_regime():
    config = default_world_config()
    classes = [r["disruption_class"] for r in config["regimes"]]
    assert classes.count("port_congestion") == 2  # pre-shift and post-shift regimes
