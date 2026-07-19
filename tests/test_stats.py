import math

import pytest

from eagle_eye.stats import (
    DeterministicRng,
    _betainc_regularized,
    brier,
    expected_calibration_error,
    interval_coverage,
    log_loss,
    log_sum_exp,
    norm_cdf,
    norm_crps,
    norm_logpdf,
    norm_pdf,
    norm_ppf,
    pit_values,
    stable_seed,
    t_cdf,
    t_crps,
    t_logpdf,
    t_ppf,
    trapezoid,
)


def test_normal_cdf_matches_reference_values():
    # Reference values from standard normal tables (15+ digits, scipy-verified constants)
    assert norm_cdf(0.0) == pytest.approx(0.5, abs=1e-15)
    assert norm_cdf(1.0) == pytest.approx(0.8413447460685429, abs=1e-12)
    assert norm_cdf(-1.96) == pytest.approx(0.024997895148220435, abs=1e-12)
    assert norm_cdf(3.0, mu=1.0, sigma=2.0) == pytest.approx(norm_cdf(1.0), abs=1e-15)


def test_normal_ppf_matches_reference_and_round_trips():
    assert norm_ppf(0.975) == pytest.approx(1.959963984540054, abs=1e-9)
    assert norm_ppf(0.01) == pytest.approx(-2.3263478740408408, abs=1e-9)
    assert norm_ppf(0.5) == pytest.approx(0.0, abs=1e-12)
    for p in (1e-6, 0.001, 0.2, 0.5, 0.8, 0.999, 1 - 1e-6):
        assert norm_cdf(norm_ppf(p)) == pytest.approx(p, abs=1e-11)
    with pytest.raises(ValueError):
        norm_ppf(0.0)


def test_normal_crps_known_value_and_minimum_at_center():
    # CRPS of N(0,1) at y=0 equals 2*phi(0) - 1/sqrt(pi)
    expected = 2.0 / math.sqrt(2.0 * math.pi) - 1.0 / math.sqrt(math.pi)
    assert norm_crps(0.0, 0.0, 1.0) == pytest.approx(expected, abs=1e-14)
    assert norm_crps(0.0, 0.0, 1.0) < norm_crps(1.5, 0.0, 1.0)
    # Scale equivariance: CRPS(sy; smu, ssigma) = s * CRPS(y; mu, sigma)
    assert norm_crps(3.0, 1.0, 2.0) == pytest.approx(2.0 * norm_crps(1.5, 0.5, 1.0), rel=1e-12)


def test_incomplete_beta_exact_identities():
    for x in (0.05, 0.3, 0.5, 0.77, 0.99):
        assert _betainc_regularized(1.0, 1.0, x) == pytest.approx(x, abs=1e-12)
        assert _betainc_regularized(1.0, 3.0, x) == pytest.approx(1 - (1 - x) ** 3, abs=1e-12)
        assert _betainc_regularized(2.0, 2.0, x) == pytest.approx(x * x * (3 - 2 * x), abs=1e-12)


def test_student_t_exact_low_df_values():
    # df=1 is Cauchy: F(x) = 1/2 + atan(x)/pi
    assert t_cdf(1.0, 1.0) == pytest.approx(0.75, abs=1e-12)
    assert t_ppf(0.75, 1.0) == pytest.approx(1.0, abs=1e-9)
    # df=2 closed form: F(x) = 1/2 + x / (2*sqrt(2 + x^2))
    assert t_cdf(2.0, 2.0) == pytest.approx(0.5 + 2.0 / (2.0 * math.sqrt(6.0)), abs=1e-12)
    # Critical value: t_{0.975, df=10} = 2.2281388519649385
    assert t_ppf(0.975, 10.0) == pytest.approx(2.2281388519649385, abs=1e-8)
    # Symmetry
    assert t_cdf(-1.3, 7.0) == pytest.approx(1.0 - t_cdf(1.3, 7.0), abs=1e-12)


def test_student_t_pdf_integrates_to_cdf():
    df = 5.0
    integral = trapezoid(lambda x: math.exp(t_logpdf(x, df)), -60.0, 1.2, n=20000)
    assert integral == pytest.approx(t_cdf(1.2, df), abs=1e-6)


def test_student_t_crps_converges_to_normal_for_large_df():
    y, mu, sigma = 0.7, 0.2, 1.3
    assert t_crps(y, 1e7, mu, sigma) == pytest.approx(norm_crps(y, mu, sigma), abs=1e-6)
    with pytest.raises(ValueError):
        t_crps(0.0, 1.0)


def test_student_t4_cdf_matches_exact_closed_form():
    # For df=4 the CDF has the exact form 1/2 + (3/4)(s - s^3/3), s = x/sqrt(x^2+4)
    for x in (-6.0, -1.7, -0.2, 0.0, 0.4, 1.1, 2.9, 8.0):
        s = x / math.sqrt(x * x + 4.0)
        exact = 0.5 + 0.75 * (s - s ** 3 / 3.0)
        assert t_cdf(x, 4.0) == pytest.approx(exact, abs=1e-12)


def test_student_t_crps_exact_anchor_and_pinball_cross_check():
    # Exact hand-derived anchor: CRPS(0; t_df=4) = 1 - (4/3) B(.5,3.5)/B(.5,2)^2
    b_a = math.exp(math.lgamma(0.5) + math.lgamma(3.5) - math.lgamma(4.0))
    b_b = math.exp(math.lgamma(0.5) + math.lgamma(2.0) - math.lgamma(2.5))
    anchor = 2.0 * (3.0 / 8.0) * (4.0 / 3.0) - (4.0 / 3.0) * b_a / (b_b * b_b)
    assert t_crps(0.0, 4.0) == pytest.approx(anchor, abs=1e-12)

    # Independent representation: CRPS = int_0^1 2 rho_alpha(y - q_alpha) d alpha
    y, df, mu, sigma = 1.1, 4.0, 0.3, 0.9

    def pinball(alpha: float) -> float:
        q = t_ppf(alpha, df, mu, sigma)
        u = y - q
        return 2.0 * u * (alpha - (1.0 if u < 0 else 0.0))

    eps = 1e-7
    numeric = trapezoid(pinball, eps, 1.0 - eps, n=40000)
    assert t_crps(y, df, mu, sigma) == pytest.approx(numeric, abs=5e-4)


def test_scoring_rules_basics():
    assert brier(0.8, True) == pytest.approx(0.04)
    assert brier(0.8, False) == pytest.approx(0.64)
    assert log_loss(0.5, True) == pytest.approx(math.log(2.0))
    assert log_loss(1.0, True) == pytest.approx(0.0, abs=1e-9)
    with pytest.raises(ValueError):
        brier(1.5, True)
    assert interval_coverage([True, True, False, True]) == pytest.approx(0.75)


def test_expected_calibration_error_perfect_and_biased():
    probs = [0.05] * 100 + [0.95] * 100
    outcomes = [False] * 95 + [True] * 5 + [True] * 95 + [False] * 5
    assert expected_calibration_error(probs, outcomes) == pytest.approx(0.0, abs=1e-9)
    biased = expected_calibration_error([0.9] * 100, [True] * 50 + [False] * 50)
    assert biased == pytest.approx(0.4, abs=1e-9)


def test_pit_uniformity_summary():
    uniform = [i / 200.0 + 1.0 / 400.0 for i in range(200)]
    summary = pit_values(uniform)
    assert summary["mean"] == pytest.approx(0.5, abs=1e-9)
    assert summary["cvm"] < 0.01
    concentrated = pit_values([0.5] * 200)
    assert concentrated["cvm"] > summary["cvm"]


def test_log_sum_exp_stability():
    assert log_sum_exp([-1000.0, -1000.0]) == pytest.approx(-1000.0 + math.log(2.0))
    assert log_sum_exp([0.0]) == pytest.approx(0.0)


def test_deterministic_rng_reproducible_and_sane():
    a = DeterministicRng(42)
    b = DeterministicRng(42)
    seq_a = [a.next_u64() for _ in range(5)]
    seq_b = [b.next_u64() for _ in range(5)]
    assert seq_a == seq_b
    assert DeterministicRng(43).next_u64() != seq_a[0]
    rng = DeterministicRng(7)
    normals = [rng.normal() for _ in range(20000)]
    mean = sum(normals) / len(normals)
    var = sum((v - mean) ** 2 for v in normals) / len(normals)
    assert mean == pytest.approx(0.0, abs=0.03)
    assert var == pytest.approx(1.0, abs=0.05)
    uniforms = [DeterministicRng(9).uniform() for _ in range(1)]
    assert 0.0 <= uniforms[0] < 1.0


def test_deterministic_rng_beta_moments():
    rng = DeterministicRng(11)
    samples = [rng.beta(2.0, 5.0) for _ in range(4000)]
    mean = sum(samples) / len(samples)
    assert mean == pytest.approx(2.0 / 7.0, abs=0.02)
    assert all(0.0 < s < 1.0 for s in samples)


def test_stable_seed_is_canonical():
    assert stable_seed("a", 1) == stable_seed("a", 1)
    assert stable_seed("a", 1) != stable_seed("a", 2)
    assert 0 <= stable_seed("x") < (1 << 64)


def test_norm_logpdf_matches_pdf():
    assert math.exp(norm_logpdf(0.4, 0.1, 2.0)) == pytest.approx(norm_pdf(0.4, 0.1, 2.0), rel=1e-12)
