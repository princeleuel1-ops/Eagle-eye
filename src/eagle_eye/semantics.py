from pathlib import Path


def inspect_frontend_contract(web_dir: Path) -> dict[str, bool]:
    content = "\n".join(
        p.read_text(errors="ignore")
        for p in web_dir.rglob("*")
        if p.is_file() and p.suffix in {".html", ".js", ".css"}
    )
    return {
        "has_digital_twin": 'id="digital-twin"' in content,
        "has_graph_layer": 'id="network-layer"' in content,
        "has_geo_layer": 'id="geo-layer"' in content,
        "has_evidence_drawer": 'id="evidence-drawer"' in content,
        "has_fixture_label": "FIXTURE" in content,
        "has_action_approval": "pending_approval" in content or "Approve action" in content,
        "has_scenario_comparison": 'id="scenarios"' in content and "SCENARIO COMPARISON" in content,
        "has_recursive_court": 'id="court"' in content and "RECURSIVE BENCHMARK COURT" in content,
        "has_governance_harness": 'id="governance"' in content and "DUAL CONTROL" in content,
        "has_audit_commitment": "AUDIT CHAIN" in content and "audit.head" in content,
        "has_verified_identity": "IDENTITIES" in content and "identity_harness.principals_verified" in content,
        "has_policy_receipts": "POLICY ·" in content and "policy_bundle.release" in content and "2 ALLOW RECEIPTS" in content,
        "has_posterior_panel": 'id="posterior"' in content and "POSTERIOR INTELLIGENCE" in content,
        "has_interval_bands": "interval-band" in content and "p_exceeds_days" in content,
        "has_support_and_shift": "support_state" in content and "shift_score" in content,
        "has_prior_provenance": 'id="prior-provenance"' in content and "included_prior_task_ids" in content,
        "has_calibration_state": "calibration_receipt" in content and "coverage80" in content,
        "has_abstention_state": "abstained" in content and "ABSTAINED" in content,
        "has_falsification_note": "what_would_falsify" in content,
        "has_commitment_recompute": "recomputeCommitment" in content and "quantizeMicro" in content,
        "has_uncertainty_labels": "KNOWN" in content and "ASSUMED" in content and "UNKNOWN" in content,
        "has_evolution_panel": 'id="evolution"' in content and "SEALED EVOLUTION" in content,
        "has_lineage_and_budget": "LINEAGE" in content and "CHALLENGER BUDGET" in content and "alpha" in content,
        "has_guarantee_state": "CONFORMAL" in content and "GUARANTEE_ACTIVE" in content,
        "has_off_policy_state": "off-policy" in content or "off_policy" in content,
        "has_voi_display": "VOI" in content and "evoi_usd" in content,
        "has_honest_evolution_claim": "GOVERNED CANDIDATE EVOLUTION" in content and "claim_supported" in content,
        "has_external_action_false": "EXTERNAL_ACTION" in content and "FALSE" in content,
    }
