from pathlib import Path
from eagle_eye.semantics import inspect_frontend_contract


def test_frontend_is_a_connected_twin_not_a_table_only_dashboard():
    result = inspect_frontend_contract(Path("web"))
    assert result["has_digital_twin"]
    assert result["has_graph_layer"]
    assert result["has_geo_layer"]
    assert result["has_evidence_drawer"]
    assert result["has_fixture_label"]
    assert result["has_action_approval"]


def test_frontend_renders_posterior_uncertainty_contract():
    result = inspect_frontend_contract(Path("web"))
    assert result["has_posterior_panel"]
    assert result["has_interval_bands"]
    assert result["has_support_and_shift"]
    assert result["has_prior_provenance"]
    assert result["has_calibration_state"]
    assert result["has_abstention_state"]
    assert result["has_falsification_note"]
    assert result["has_commitment_recompute"]
    assert result["has_uncertainty_labels"]


def test_frontend_renders_sealed_evolution_contract():
    result = inspect_frontend_contract(Path("web"))
    assert result["has_evolution_panel"]
    assert result["has_lineage_and_budget"]
    assert result["has_guarantee_state"]
    assert result["has_off_policy_state"]
    assert result["has_voi_display"]
    assert result["has_honest_evolution_claim"]
    assert result["has_external_action_false"]
