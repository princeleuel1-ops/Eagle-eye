"""V7 e-process ledger: exact math, supermartingale validity, Ville frequency,
power sanity, and fail-closed admission semantics."""

import math

import pytest

from eagle_eye.eprocess import (
    EPROCESS_ALPHA_MICRO,
    EPROCESS_LOG_THRESHOLD_MICRO,
    EProcessLedger,
    binomial_mixture_log_e,
    log_e_micro,
    sign_counts_from_diffs_micro,
    stream_id,
)
from eagle_eye.stats import DeterministicRng, stable_seed


# ---------- exact closed forms ------------------------------------------------

def test_single_trial_closed_forms():
    assert math.exp(binomial_mixture_log_e(1, 0)) == pytest.approx(1.5, abs=1e-9)
    assert math.exp(binomial_mixture_log_e(0, 1)) == pytest.approx(0.5, abs=1e-9)


def test_empty_evidence_is_neutral():
    assert binomial_mixture_log_e(0, 0) == 0.0
    assert log_e_micro(0, 0) == 0


def test_negative_counts_refused():
    with pytest.raises(ValueError):
        binomial_mixture_log_e(-1, 3)


def test_threshold_is_ln_inverse_alpha_in_micro():
    assert EPROCESS_ALPHA_MICRO == 50_000
    assert EPROCESS_LOG_THRESHOLD_MICRO == round(math.log(1e6 / EPROCESS_ALPHA_MICRO) * 1e6)


def test_monotone_in_wins():
    m = 40
    values = [binomial_mixture_log_e(k, m - k) for k in range(m + 1)]
    assert values == sorted(values)
    assert values[-1] > EPROCESS_LOG_THRESHOLD_MICRO / 1e6  # 40/40 wins alone is decisive


# ---------- e-value validity (the theorem, checked by enumeration) -------------

@pytest.mark.parametrize("m", [1, 2, 3, 5, 8, 12, 16])
def test_expectation_exactly_one_at_null_boundary(m):
    exp_e = sum(math.comb(m, k) * 0.5 ** m * math.exp(binomial_mixture_log_e(k, m - k))
                for k in range(m + 1))
    assert exp_e == pytest.approx(1.0, abs=1e-9)


@pytest.mark.parametrize("theta", [0.05, 0.2, 0.35, 0.45, 0.5])
def test_expectation_at_most_one_everywhere_under_null(theta):
    m = 14
    exp_e = sum(math.comb(m, k) * theta ** k * (1 - theta) ** (m - k)
                * math.exp(binomial_mixture_log_e(k, m - k)) for k in range(m + 1))
    assert exp_e <= 1.0 + 1e-9


def test_ville_crossing_frequency_under_null():
    """Time-uniform guard: fraction of null streams whose RUNNING wealth ever
    reaches 1/alpha across 10 sequential runs stays near/below alpha.
    Deterministic seeded simulation — a regression pin on validity."""
    rng = DeterministicRng(stable_seed("eprocess-null-battery", 1))
    streams, runs, m = 300, 10, 30
    crossings = 0
    for s in range(streams):
        wealth_log_micro = 0
        crossed = False
        for r in range(runs):
            wins = sum(1 for _ in range(m) if rng.choice_index(2) == 1)
            wealth_log_micro += log_e_micro(wins, m - wins)
            if wealth_log_micro >= EPROCESS_LOG_THRESHOLD_MICRO:
                crossed = True
                break
        crossings += crossed
    # alpha = 0.05 -> expect <= ~15/300; allow Monte-Carlo slack, never > 2*alpha
    assert crossings <= streams * EPROCESS_ALPHA_MICRO / 1e6 * 2


def test_power_under_true_advantage():
    """A challenger that truly wins 66% of cases should usually cross within
    10 runs of 30 cases — evidence ACCUMULATES instead of dying per run."""
    rng = DeterministicRng(stable_seed("eprocess-power-battery", 1))
    streams, runs, m = 40, 10, 30
    crossed = 0
    for s in range(streams):
        wealth_log_micro = 0
        for r in range(runs):
            wins = sum(1 for _ in range(m) if rng.choice_index(100) < 66)
            wealth_log_micro += log_e_micro(wins, m - wins)
            if wealth_log_micro >= EPROCESS_LOG_THRESHOLD_MICRO:
                crossed += 1
                break
    assert crossed >= streams // 2


# ---------- counts + identities -------------------------------------------------

def test_sign_counts_and_tie_handling():
    counts = sign_counts_from_diffs_micro([-3, -1, 0, 2, 0, -5])
    assert counts == {"wins": 3, "losses": 1, "ties": 2, "n_cases": 6}


def test_stream_id_binds_both_configs():
    a = {"selector.k_max": 10}
    b = {"selector.k_max": 12}
    assert stream_id(a, b) != stream_id(b, a)
    assert stream_id(a, b) == stream_id(dict(a), dict(b))
    assert stream_id(a, b).startswith("strm-")


def test_log_e_micro_is_deterministic_integer():
    v1, v2 = log_e_micro(21, 9), log_e_micro(21, 9)
    assert isinstance(v1, int) and v1 == v2 and v1 > 0


# ---------- fail-closed admission ------------------------------------------------

def test_admission_refused_without_replay_pass():
    ledger = EProcessLedger()
    with pytest.raises(ValueError, match="ADMISSION_REFUSED"):
        ledger.admit_run({}, bundle_sha256="0" * 64, replay_passed=False,
                         replay_report={"returncode": 1})


def test_empty_ledger_reports_no_crossings_and_verifies():
    ledger = EProcessLedger()
    assert ledger.standing() == []
    assert ledger.crossings() == []
    assert ledger.verify_chain() is True
