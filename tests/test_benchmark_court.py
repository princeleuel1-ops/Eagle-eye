import json
from pathlib import Path

from eagle_eye.benchmark import evaluate_mutation, run_court


def test_beneficial_mutation_is_promoted_with_receipt(tmp_path: Path):
    baseline = {
        "development_accuracy": 0.72,
        "holdout_accuracy": 0.70,
        "safety_score": 1.0,
        "calibration_error": 0.18,
        "latency_ms": 180,
        "cost_usd": 0.04,
    }
    candidate = {
        "development_accuracy": 0.84,
        "holdout_accuracy": 0.81,
        "safety_score": 1.0,
        "calibration_error": 0.12,
        "latency_ms": 195,
        "cost_usd": 0.045,
    }
    decision = evaluate_mutation("evidence-aware-ranking-v2", baseline, candidate)
    assert decision["status"] == "promote"
    assert decision["target_improved"] is True
    assert decision["holdout_non_regression"] is True
    assert decision["safety_non_regression"] is True
    assert decision["receipt_id"].startswith("mutation-")


def test_attractive_harmful_mutation_is_rejected():
    baseline = {
        "development_accuracy": 0.72,
        "holdout_accuracy": 0.70,
        "safety_score": 1.0,
        "calibration_error": 0.18,
        "latency_ms": 180,
        "cost_usd": 0.04,
    }
    candidate = {
        "development_accuracy": 0.96,
        "holdout_accuracy": 0.61,
        "safety_score": 0.92,
        "calibration_error": 0.27,
        "latency_ms": 120,
        "cost_usd": 0.02,
    }
    decision = evaluate_mutation("overfit-fast-route-v9", baseline, candidate)
    assert decision["status"] == "reject"
    assert decision["target_improved"] is True
    assert decision["holdout_non_regression"] is False
    assert decision["safety_non_regression"] is False
    assert "holdout_regression" in decision["reasons"]
    assert "safety_regression" in decision["reasons"]


def test_court_emits_both_required_recursive_proofs(tmp_path: Path):
    spec = Path(__file__).resolve().parents[1] / "benchmarks/eefb-v0.1.json"
    receipt = run_court(spec, tmp_path)
    assert receipt["benchmark"] == "EEFB-v0.1"
    assert receipt["proofs"]["beneficial_mutation_promoted"] is True
    assert receipt["proofs"]["harmful_mutation_rejected"] is True
    persisted = json.loads((tmp_path / "court-receipt.json").read_text())
    assert persisted["court_receipt_id"] == receipt["court_receipt_id"]
