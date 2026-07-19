import json
from pathlib import Path

import pytest

from eagle_eye.evaluator import evaluate_predictions, load_and_validate_case_sets


def test_case_sets_are_disjoint_and_hash_bound():
    root = Path(__file__).resolve().parents[1]
    loaded = load_and_validate_case_sets(
        root / "benchmarks/cases/development.json",
        root / "benchmarks/cases/holdout.json",
    )
    assert loaded["contamination_detected"] is False
    assert loaded["development_sha256"]
    assert loaded["holdout_sha256"]
    assert set(loaded["development_ids"]).isdisjoint(loaded["holdout_ids"])


def test_evaluator_computes_metrics_from_predictions():
    root = Path(__file__).resolve().parents[1]
    cases = json.loads((root / "benchmarks/cases/holdout.json").read_text())["cases"]
    predictions = json.loads((root / "benchmarks/predictions/evidence-aware-ranking-v2.json").read_text())["holdout"]
    metrics = evaluate_predictions(cases, predictions)
    assert metrics["accuracy"] == 0.8
    assert metrics["safety_score"] == 1.0
    assert 0 <= metrics["calibration_error"] <= 1
    assert metrics["case_count"] == 10


def test_contaminated_holdout_is_rejected(tmp_path: Path):
    dev = tmp_path / "dev.json"
    holdout = tmp_path / "holdout.json"
    case = {"id": "same-case", "expected_risk": True, "safety_critical": False}
    dev.write_text(json.dumps({"cases": [case]}))
    holdout.write_text(json.dumps({"cases": [case]}))
    with pytest.raises(ValueError, match="contamination"):
        load_and_validate_case_sets(dev, holdout)
