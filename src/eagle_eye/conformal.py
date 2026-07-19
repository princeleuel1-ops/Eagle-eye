"""Split-conformal calibration with honest guarantee states.

The finite-sample guarantee (coverage >= target with calibration size n using
the ceil((n+1)*(1-alpha)) order statistic) holds ONLY under exchangeability of
the normalized nonconformity scores. This module never claims coverage under
arbitrary shift: a detected regime shift, low effective sample, or
contamination SUSPENDS the guarantee (fail closed), preserving the last valid
receipt. A shift-weighted variant exists but a generic shift score is NOT a
valid density ratio, so its output is at best GUARANTEE_CONDITIONAL with its
assumptions recorded.
"""

from __future__ import annotations

import math
from typing import Any

from .predictors import LogScaleDist
from .prior_registry import canonical_bytes, sha256_hex

CONFORMAL_SPEC = "eagle-eye-conformal/1.0"
GUARANTEE_STATES = (
    "GUARANTEE_ACTIVE", "GUARANTEE_CONDITIONAL", "GUARANTEE_SUSPENDED_SHIFT",
    "GUARANTEE_SUSPENDED_LOW_EFFECTIVE_SAMPLE", "GUARANTEE_SUSPENDED_CONTAMINATION",
    "GUARANTEE_NOT_APPLICABLE",
)
MIN_CALIBRATION_N = 20
SHIFT_SUSPEND = 0.80


def nonconformity(y: float, dist: LogScaleDist) -> float:
    """Scale-normalized absolute residual on log-delay."""
    return abs(y - dist.loc) / dist.scale


def calibrate(pairs: list[tuple[float, LogScaleDist]], *, target_coverage: float = 0.8) -> dict[str, Any]:
    """Fit the split-conformal quantile from (realized, committed dist) pairs."""
    if not 0.0 < target_coverage < 1.0:
        raise ValueError("target_coverage must be in (0,1)")
    scores = sorted(nonconformity(y, dist) for y, dist in pairs)
    n = len(scores)
    receipt: dict[str, Any] = {
        "spec": CONFORMAL_SPEC,
        "target_coverage_micro": int(round(target_coverage * 1e6)),
        "calibration_sample_size": n,
        "nonconformity_score": "abs(y - loc)/scale on log-delay",
        "quantile_rule": "order statistic ceil((n+1)*coverage) of calibration scores",
    }
    if n < MIN_CALIBRATION_N:
        receipt.update({"q_hat_micro": None,
                        "state_if_used": "GUARANTEE_SUSPENDED_LOW_EFFECTIVE_SAMPLE"})
        receipt["receipt_sha256"] = sha256_hex(canonical_bytes(receipt))
        return receipt
    rank = math.ceil((n + 1) * target_coverage)
    if rank > n:
        # guarantee unattainable at this n (needs larger calibration set)
        receipt.update({"q_hat_micro": None,
                        "state_if_used": "GUARANTEE_SUSPENDED_LOW_EFFECTIVE_SAMPLE"})
        receipt["receipt_sha256"] = sha256_hex(canonical_bytes(receipt))
        return receipt
    q_hat = scores[rank - 1]
    # Conservative-upward micro rounding: rounding DOWN could shrink the
    # threshold below the exact order statistic and void the guarantee (B10).
    import math as _math
    receipt.update({"q_hat_micro": int(_math.ceil(q_hat * 1e6)), "state_if_used": "GUARANTEE_ACTIVE"})
    receipt["receipt_sha256"] = sha256_hex(canonical_bytes(receipt))
    return receipt


def conformal_interval(dist: LogScaleDist, calibration: dict[str, Any], *,
                       shift_score: float | None, contamination: bool = False) -> dict[str, Any]:
    """Emit the conformal interval (log and day scale) with its guarantee state."""
    q_micro = calibration.get("q_hat_micro")
    if q_micro is None:
        state = calibration.get("state_if_used", "GUARANTEE_NOT_APPLICABLE")
        return {"state": state, "interval_days": None,
                "calibration_receipt_sha256": calibration["receipt_sha256"],
                "reason": "no valid conformal quantile at this calibration size"}
    if contamination:
        state = "GUARANTEE_SUSPENDED_CONTAMINATION"
    elif shift_score is not None and shift_score >= SHIFT_SUSPEND:
        state = "GUARANTEE_SUSPENDED_SHIFT"
    else:
        state = "GUARANTEE_ACTIVE"
    # Weighted conformal REMOVED (audit blocker 9): the previous path changed
    # labels without applying weights. Reintroduction requires supplied,
    # validated density-ratio weights with effective-sample diagnostics.
    q = q_micro / 1e6
    lo, hi = dist.loc - q * dist.scale, dist.loc + q * dist.scale
    payload: dict[str, Any] = {
        "state": state,
        "target_coverage_micro": calibration["target_coverage_micro"],
        "q_hat_micro": q_micro,
        "interval_log": {"low": round(lo, 8), "high": round(hi, 8)},
        "interval_days": {"low": round(math.exp(lo), 3), "high": round(math.exp(hi), 3)},
        "calibration_receipt_sha256": calibration["receipt_sha256"],
    }
    if state == "GUARANTEE_SUSPENDED_SHIFT":
        payload["operator_note"] = (
            "exchangeability with the calibration sample is not supported at this shift level; "
            "interval shown is the last-calibrated shape and carries NO finite-sample guarantee; "
            "recalibrate on an eligible sample from the new regime")
    return payload


def evaluate_coverage(pairs: list[tuple[float, LogScaleDist, str]], calibration: dict[str, Any]) -> dict[str, Any]:
    """Empirical coverage on held-out (y, dist, group) pairs.

    CONTRACT (audit blocker 8): callers MUST pass pairs DISJOINT from the
    calibration sample. Calibration-set coverage is not an evaluation and must
    never be published as one."""
    q_micro = calibration.get("q_hat_micro")
    if q_micro is None:
        return {"empirical_coverage_micro": None, "by_group": {}, "n": 0}
    q = q_micro / 1e6
    hits: dict[str, list[bool]] = {}
    for y, dist, group in pairs:
        covered = abs(y - dist.loc) / dist.scale <= q
        hits.setdefault("__all__", []).append(covered)
        hits.setdefault(group, []).append(covered)
    def rate(rows: list[bool]) -> int:
        return int(round(1e6 * sum(rows) / len(rows)))
    return {
        "empirical_coverage_micro": rate(hits["__all__"]),
        "n": len(hits["__all__"]),
        "by_group": {g: {"coverage_micro": rate(r), "n": len(r)}
                     for g, r in sorted(hits.items()) if g != "__all__"},
    }
