import json
from pathlib import Path

from eagle_eye.ingestion import ingest_directory
from eagle_eye.kernel import build_run


def test_csv_directory_becomes_evidence_bound_preflight():
    root = Path(__file__).resolve().parents[1]
    payload = ingest_directory(root / "fixtures" / "po17")
    run = build_run(payload)

    assert payload["mode"] == "FIXTURE"
    assert payload["purchase_orders"][0]["id"] == "PO-17"
    assert payload["components"][0]["id"] == "MCU-42"
    assert run["scenarios"][0]["name"] == "baseline"
    assert run["scenarios"][1]["name"] == "disruption"
    assert run["scenarios"][1]["delay_days"]["high"] > run["scenarios"][0]["delay_days"]["high"]
    assert run["actions"][0]["status"] == "pending_approval"
    assert run["approval_receipts"] == []


def test_ingestion_rejects_missing_required_columns(tmp_path: Path):
    import pytest
    (tmp_path / "suppliers.csv").write_text("name,country\nNo ID,TW\n")
    with pytest.raises(ValueError, match="suppliers.csv.*id"):
        ingest_directory(tmp_path)
