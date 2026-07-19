import pytest

from eagle_eye.conformal import (
    MIN_CALIBRATION_N,
    calibrate,
    conformal_interval,
    evaluate_coverage,
    nonconformity,
)
from eagle_eye.predictors import LogScaleDist
from eagle_eye.stats import DeterministicRng


def _pairs(seed: int, n: int, *, df: float | None = None, scale: float = 0.4):
    rng = DeterministicRng(seed)
    pairs = []
    for _ in range(n):
        dist = LogScaleDist(2.5 + rng.normal(0, 0.2), scale, df=None)
        y = rng.student_t(df, dist.loc, scale) if df else rng.normal(dist.loc, scale)
        pairs.append((y, dist))
    return pairs


def test_exact_exchangeable_case_achieves_target_coverage():
    calibration = calibrate(_pairs(1, 200), target_coverage=0.8)
    assert calibration["q_hat_micro"] is not None
    fresh = [(y, d, "iid") for y, d in _pairs(2, 400)]
    result = evaluate_coverage(fresh, calibration)
    assert result["empirical_coverage_micro"] >= 780000  # finite-sample guarantee holds


def test_heavy_tails_are_distribution_free():
    calibration = calibrate(_pairs(3, 200, df=3.0), target_coverage=0.8)
    fresh = [(y, d, "t3") for y, d in _pairs(4, 400, df=3.0)]
    result = evaluate_coverage(fresh, calibration)
    assert result["empirical_coverage_micro"] >= 770000


def test_insufficient_calibration_suspends():
    calibration = calibrate(_pairs(5, MIN_CALIBRATION_N - 1))
    assert calibration["q_hat_micro"] is None
    interval = conformal_interval(LogScaleDist(2.5, 0.4), calibration, shift_score=0.1)
    assert interval["state"] == "GUARANTEE_SUSPENDED_LOW_EFFECTIVE_SAMPLE"
    assert interval["interval_days"] is None


def test_unattainable_target_coverage_suspends():
    calibration = calibrate(_pairs(6, 25), target_coverage=0.99)  # rank 26 > 25
    assert calibration["q_hat_micro"] is None
    assert calibration["state_if_used"] == "GUARANTEE_SUSPENDED_LOW_EFFECTIVE_SAMPLE"
    with pytest.raises(ValueError):
        calibrate(_pairs(6, 25), target_coverage=1.5)


def test_shift_suspends_guarantee_and_preserves_receipt():
    calibration = calibrate(_pairs(7, 100))
    interval = conformal_interval(LogScaleDist(2.5, 0.4), calibration, shift_score=0.95)
    assert interval["state"] == "GUARANTEE_SUSPENDED_SHIFT"
    assert "NO finite-sample guarantee" in interval["operator_note"]
    assert interval["calibration_receipt_sha256"] == calibration["receipt_sha256"]


def test_contamination_suspends():
    calibration = calibrate(_pairs(8, 100))
    interval = conformal_interval(LogScaleDist(2.5, 0.4), calibration, shift_score=0.1,
                                  contamination=True)
    assert interval["state"] == "GUARANTEE_SUSPENDED_CONTAMINATION"


def test_fake_weighted_conformal_is_removed():
    """Audit blocker 9: the label-only weighted path is GONE; passing weighted
    raises rather than silently mislabeling."""
    calibration = calibrate(_pairs(9, 100))
    with pytest.raises(TypeError):
        conformal_interval(LogScaleDist(2.5, 0.4), calibration, shift_score=0.4, weighted=True)


def test_quantile_rounding_is_conservative_upward():
    """Audit blocker 10: micro rounding must never shrink the threshold."""
    dist = LogScaleDist(0.0, 1.0)
    pairs = [(0.1234567891, dist)] * 60  # exact score has >6 decimals
    calibration = calibrate(pairs, target_coverage=0.8)
    exact = 0.1234567891
    assert calibration["q_hat_micro"] >= exact * 1e6  # ceil, not round-down
    assert calibration["q_hat_micro"] == 123457


def test_calibration_set_reuse_is_biased_vs_disjoint():
    """Audit blocker 8: coverage on the calibration set itself over-states
    coverage relative to disjoint evaluation; publishing it is forbidden."""
    cal_pairs = _pairs(21, 120)
    calibration = calibrate(cal_pairs, target_coverage=0.8)
    reuse = evaluate_coverage([(y, d, "reuse") for y, d in cal_pairs], calibration)
    disjoint = evaluate_coverage([(y, d, "fresh") for y, d in _pairs(22, 400)], calibration)
    assert reuse["empirical_coverage_micro"] >= disjoint["empirical_coverage_micro"] - 20000


def test_corrupted_calibration_labels_inflate_quantile_not_break():
    clean = calibrate(_pairs(10, 100))
    corrupted_pairs = _pairs(10, 100)
    corrupted_pairs[:10] = [(y + 8.0, d) for y, d in corrupted_pairs[:10]]
    corrupted = calibrate(corrupted_pairs)
    assert corrupted["q_hat_micro"] > clean["q_hat_micro"]  # wider, never sharper


def test_ties_and_degenerate_predictor_are_stable():
    dist = LogScaleDist(2.5, 0.4)
    tied = [(2.5 + 0.1, dist)] * 50  # identical scores
    calibration = calibrate(tied)
    assert calibration["q_hat_micro"] is not None
    tiny = LogScaleDist(2.5, 1e-6)
    assert nonconformity(2.6, tiny) > 1e4  # degenerate scale -> huge score, finite


def test_sharpened_predictor_damages_conformal_coverage_visibly():
    """A candidate that improves point accuracy but shrinks its scale breaks
    the exchangeability between calibration and use -> coverage drops. This is
    exactly why recalibration is mandatory after any promotion."""
    calibration = calibrate(_pairs(11, 200))
    fresh = [(y, LogScaleDist(d.loc, d.scale * 0.45), "sharpened") for y, d in _pairs(12, 300)]
    result = evaluate_coverage(fresh, calibration)
    assert result["empirical_coverage_micro"] < 780000


def test_coverage_by_group_reported():
    calibration = calibrate(_pairs(13, 150))
    fresh = [(y, d, "regA") for y, d in _pairs(14, 100)] + \
            [(y, d, "regB") for y, d in _pairs(15, 100)]
    result = evaluate_coverage(fresh, calibration)
    assert set(result["by_group"]) == {"regA", "regB"}
    for group in result["by_group"].values():
        assert group["n"] == 100
