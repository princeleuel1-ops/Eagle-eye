from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_and_validate_case_sets(development_path: Path, holdout_path: Path) -> dict[str, Any]:
    development = json.loads(development_path.read_text())["cases"]
    holdout = json.loads(holdout_path.read_text())["cases"]
    development_ids = [case["id"] for case in development]
    holdout_ids = [case["id"] for case in holdout]
    overlap = sorted(set(development_ids) & set(holdout_ids))
    fingerprints = lambda rows: {hashlib.sha256(json.dumps({k:v for k,v in row.items() if k != "id"}, sort_keys=True).encode()).hexdigest() for row in rows}
    content_overlap = fingerprints(development) & fingerprints(holdout)
    if overlap or content_overlap:
        raise ValueError(f"benchmark contamination detected: ids={overlap}, content_overlap={len(content_overlap)}")
    return {
        "development": development,
        "holdout": holdout,
        "development_ids": development_ids,
        "holdout_ids": holdout_ids,
        "development_sha256": _digest(development_path),
        "holdout_sha256": _digest(holdout_path),
        "contamination_detected": False,
    }


def evaluate_predictions(cases: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> dict[str, Any]:
    expected_ids = {case["id"] for case in cases}
    by_id = {prediction["id"]: prediction for prediction in predictions}
    if set(by_id) != expected_ids:
        raise ValueError("prediction IDs must exactly match case IDs")
    correct = 0
    squared_error = 0.0
    safety_total = 0
    safety_correct = 0
    for case in cases:
        probability = float(by_id[case["id"]]["probability"])
        if not 0 <= probability <= 1:
            raise ValueError("probability must be in [0, 1]")
        expected = bool(case["expected_risk"])
        predicted = probability >= 0.5
        correct += predicted == expected
        squared_error += (probability - float(expected)) ** 2
        if case["safety_critical"]:
            safety_total += 1
            safety_correct += predicted == expected
    return {
        "accuracy": round(correct / len(cases), 4),
        "safety_score": round(safety_correct / safety_total, 4) if safety_total else 1.0,
        "calibration_error": round(squared_error / len(cases), 4),
        "case_count": len(cases),
    }


def evaluate_candidate(case_sets: dict[str, Any], prediction_path: Path) -> dict[str, Any]:
    candidate = json.loads(prediction_path.read_text())
    development = evaluate_predictions(case_sets["development"], candidate["development"])
    holdout = evaluate_predictions(case_sets["holdout"], candidate["holdout"])
    return {
        "candidate": candidate["candidate"],
        "prediction_sha256": _digest(prediction_path),
        "development_accuracy": development["accuracy"],
        "holdout_accuracy": holdout["accuracy"],
        "safety_score": holdout["safety_score"],
        "calibration_error": holdout["calibration_error"],
        "latency_ms": candidate["latency_ms"],
        "cost_usd": candidate["cost_usd"],
        "development_case_count": development["case_count"],
        "holdout_case_count": holdout["case_count"],
    }
