from eagle_eye.kernel import build_run


def test_build_run_creates_traceable_graph_risk_action_and_evidence():
    fixture = {
        "mode": "FIXTURE",
        "suppliers": [{"id": "sup-1", "name": "Aster Components", "country": "TW"}],
        "products": [{"id": "prod-1", "name": "Edge Controller", "revenue_at_risk": 420000}],
        "components": [{"id": "cmp-1", "name": "Control MCU", "supplier_id": "sup-1", "product_id": "prod-1"}],
        "purchase_orders": [{"id": "po-1", "product_id": "prod-1", "supplier_id": "sup-1", "value": 180000}],
        "events": [{"id": "evt-1", "supplier_id": "sup-1", "severity": 0.82, "kind": "facility_disruption", "source_id": "src-1"}],
        "sources": [{"id": "src-1", "label": "Authorized fixture advisory", "captured_at": "2026-07-12T00:00:00Z"}],
    }

    run = build_run(fixture)

    assert run["mode"] == "FIXTURE"
    assert run["graph"]["nodes"]
    assert run["graph"]["edges"]
    assert run["risks"][0]["evidence_ids"] == ["src-1"]
    assert run["risks"][0]["affected_purchase_orders"] == ["po-1"]
    assert run["actions"][0]["status"] == "pending_approval"
    assert run["actions"][0]["external_execution_allowed"] is False
    assert run["trace"][0]["path"] == ["src-1", "evt-1", "sup-1", "po-1", run["actions"][0]["id"]]


def test_kernel_rejects_unlabeled_or_live_fixture_data():
    import pytest
    with pytest.raises(ValueError, match="mode"):
        build_run({"suppliers": []})
    with pytest.raises(ValueError, match="FIXTURE"):
        build_run({"mode": "LIVE", "suppliers": []})
