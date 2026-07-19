from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REQUIRED_METRICS = {
    "development_accuracy",
    "holdout_accuracy",
    "safety_score",
    "calibration_error",
    "latency_ms",
    "cost_usd",
}


def _stable_id(prefix: str, value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:12]}"


def evaluate_mutation(name: str, baseline: dict[str, float], candidate: dict[str, float], *, limits: dict[str, float] | None = None) -> dict[str, Any]:
    missing = REQUIRED_METRICS - baseline.keys() | REQUIRED_METRICS - candidate.keys()
    if missing:
        raise ValueError(f"missing benchmark metrics: {', '.join(sorted(missing))}")
    limits = limits or {"max_latency_ms": 250, "max_cost_usd": 0.06}
    checks = {
        "target_improved": candidate["development_accuracy"] > baseline["development_accuracy"],
        "holdout_non_regression": candidate["holdout_accuracy"] >= baseline["holdout_accuracy"],
        "safety_non_regression": candidate["safety_score"] >= baseline["safety_score"],
        "calibration_non_regression": candidate["calibration_error"] <= baseline["calibration_error"],
        "latency_within_budget": candidate["latency_ms"] <= limits["max_latency_ms"],
        "cost_within_budget": candidate["cost_usd"] <= limits["max_cost_usd"],
    }
    reason_map = {
        "target_improved": "target_not_improved",
        "holdout_non_regression": "holdout_regression",
        "safety_non_regression": "safety_regression",
        "calibration_non_regression": "calibration_regression",
        "latency_within_budget": "latency_budget_exceeded",
        "cost_within_budget": "cost_budget_exceeded",
    }
    reasons = [reason_map[key] for key, passed in checks.items() if not passed]
    payload = {
        "mutation": name,
        "status": "promote" if all(checks.values()) else "reject",
        "baseline": baseline,
        "candidate": candidate,
        **checks,
        "reasons": reasons,
        "rollback_required": not all(checks.values()),
        "promotion_requires_human_approval": True,
    }
    payload["receipt_id"] = _stable_id("mutation", payload)
    return payload


def run_court(spec_path: Path, output_directory: Path) -> dict[str, Any]:
    spec = json.loads(spec_path.read_text())
    decisions = [
        evaluate_mutation(item["name"], spec["baseline"], item["metrics"], limits=spec["limits"])
        for item in spec["mutations"]
    ]
    receipt: dict[str, Any] = {
        "benchmark": spec["benchmark"],
        "benchmark_spec_sha256": hashlib.sha256(spec_path.read_bytes()).hexdigest(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "decisions": decisions,
        "proofs": {
            "beneficial_mutation_promoted": any(d["status"] == "promote" for d in decisions),
            "harmful_mutation_rejected": any(d["status"] == "reject" and d["target_improved"] for d in decisions),
        },
        "external_execution": False,
    }
    receipt["court_receipt_id"] = _stable_id("court", {k: v for k, v in receipt.items() if k != "generated_at"})
    output_directory.mkdir(parents=True, exist_ok=True)
    (output_directory / "court-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True))
    return receipt
