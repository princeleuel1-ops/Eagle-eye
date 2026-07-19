import json
from pathlib import Path

from eagle_eye.benchmark import run_court
from eagle_eye.evaluator import evaluate_candidate, load_and_validate_case_sets

root = Path(__file__).resolve().parents[1]
cases = load_and_validate_case_sets(
    root / "benchmarks/cases/development.json",
    root / "benchmarks/cases/holdout.json",
)
prediction_dir = root / "benchmarks/predictions"
baseline = evaluate_candidate(cases, prediction_dir / "baseline.json")
candidates = [
    evaluate_candidate(cases, prediction_dir / "evidence-aware-ranking-v2.json"),
    evaluate_candidate(cases, prediction_dir / "overfit-fast-route-v9.json"),
]
metric_keys = {
    "development_accuracy",
    "holdout_accuracy",
    "safety_score",
    "calibration_error",
    "latency_ms",
    "cost_usd",
}
measured_spec = {
    "benchmark": "EEFB-v0.2-measured",
    "description": "Metrics computed from versioned synthetic cases and exact-ID predictions.",
    "limits": {"max_latency_ms": 250, "max_cost_usd": 0.06},
    "case_provenance": {
        "development_sha256": cases["development_sha256"],
        "holdout_sha256": cases["holdout_sha256"],
        "development_case_count": len(cases["development"]),
        "holdout_case_count": len(cases["holdout"]),
        "contamination_detected": cases["contamination_detected"],
    },
    "baseline": {key: baseline[key] for key in metric_keys},
    "baseline_prediction_sha256": baseline["prediction_sha256"],
    "mutations": [
        {
            "name": candidate["candidate"],
            "prediction_sha256": candidate["prediction_sha256"],
            "metrics": {key: candidate[key] for key in metric_keys},
        }
        for candidate in candidates
    ],
}
output = root / "artifacts/benchmarks/latest"
output.mkdir(parents=True, exist_ok=True)
measured_spec_path = output / "measured-spec.json"
measured_spec_path.write_text(json.dumps(measured_spec, indent=2, sort_keys=True))
receipt = run_court(measured_spec_path, output)
print(f"BENCHMARK={receipt['benchmark']}")
print(f"DEVELOPMENT_CASES={len(cases['development'])}")
print(f"HOLDOUT_CASES={len(cases['holdout'])}")
print(f"CONTAMINATION_DETECTED={str(cases['contamination_detected']).lower()}")
print(f"DEVELOPMENT_SHA256={cases['development_sha256']}")
print(f"HOLDOUT_SHA256={cases['holdout_sha256']}")
print(f"BENEFICIAL_MUTATION_PROMOTED={str(receipt['proofs']['beneficial_mutation_promoted']).lower()}")
print(f"HARMFUL_MUTATION_REJECTED={str(receipt['proofs']['harmful_mutation_rejected']).lower()}")
print(f"COURT_RECEIPT_ID={receipt['court_receipt_id']}")
if cases["contamination_detected"] or not all(receipt["proofs"].values()):
    raise SystemExit(1)
