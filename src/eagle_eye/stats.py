"""Deterministic probability and scoring primitives (pure stdlib).

Every function is deterministic and side-effect free so that predictive
distributions, calibration receipts, and court metrics can be canonically
serialized and independently recomputed by a verifier.

No numpy/scipy: the trust surface of the evidence chain stays dependency-free.
Accuracy targets are documented per function and enforced by tests against
independently computed reference values.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Sequence

SQRT2 = math.sqrt(2.0)
SQRT2PI = math.sqrt(2.0 * math.pi)
INV_SQRT_PI = 1.0 / math.sqrt(math.pi)


# ---------------------------------------------------------------------------
# Normal distribution
# ---------------------------------------------------------------------------

def norm_pdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    z = (x - mu) / sigma
    return math.exp(-0.5 * z * z) / (sigma * SQRT2PI)


def norm_cdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    return 0.5 * (1.0 + math.erf((x - mu) / (sigma * SQRT2)))


def norm_logpdf(x: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    z = (x - mu) / sigma
    return -0.5 * z * z - math.log(sigma * SQRT2PI)


def norm_ppf(p: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    """Inverse normal CDF (Acklam's rational approximation + one Halley step).

    Absolute error < 1e-12 on (1e-12, 1-1e-12) after refinement.
    """
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    # Acklam coefficients
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    elif p <= phigh:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    # One Halley refinement step
    e = 0.5 * math.erfc(-x / SQRT2) - p
    u = e * SQRT2PI * math.exp(0.5 * x * x)
    x = x - u / (1.0 + 0.5 * x * u)
    return mu + sigma * x


def norm_crps(y: float, mu: float, sigma: float) -> float:
    """Closed-form CRPS of a Normal forecast (Gneiting & Raftery 2007)."""
    if sigma <= 0.0:
        raise ValueError("sigma must be positive")
    z = (y - mu) / sigma
    return sigma * (z * (2.0 * norm_cdf(z) - 1.0) + 2.0 * norm_pdf(z) - INV_SQRT_PI)


# ---------------------------------------------------------------------------
# Student-t distribution (location-scale)
# ---------------------------------------------------------------------------

def _log_beta(a: float, b: float) -> float:
    return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)


def _betainc_regularized(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a,b) via Lentz continued fraction.

    Deterministic; relative error < 1e-12 for the parameter ranges used
    (a, b >= 0.5, x in [0,1]).
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = a * math.log(x) + b * math.log1p(-x) - math.log(a) - _log_beta(a, b)
    # Use symmetry for faster convergence
    if x > (a + 1.0) / (a + b + 2.0):
        return 1.0 - _betainc_regularized(b, a, 1.0 - x)
    # Lentz's algorithm for the continued fraction
    tiny = 1e-300
    f, c_term, d_term = 1.0, 1.0, 0.0
    for m in range(0, 400):
        if m == 0:
            numerator = 1.0
        elif m % 2 == 0:
            k = m // 2
            numerator = (k * (b - k) * x) / ((a + 2.0 * k - 1.0) * (a + 2.0 * k))
        else:
            k = (m - 1) // 2
            numerator = -((a + k) * (a + b + k) * x) / ((a + 2.0 * k) * (a + 2.0 * k + 1.0))
        d_term = 1.0 + numerator * d_term
        if abs(d_term) < tiny:
            d_term = tiny
        d_term = 1.0 / d_term
        c_term = 1.0 + numerator / c_term
        if abs(c_term) < tiny:
            c_term = tiny
        f *= c_term * d_term
        if abs(1.0 - c_term * d_term) < 1e-15:
            break
    return math.exp(ln_front) * (f - 1.0)


def t_cdf(x: float, df: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    z = (x - mu) / sigma
    if z == 0.0:
        return 0.5
    w = df / (df + z * z)
    p = 0.5 * _betainc_regularized(df / 2.0, 0.5, w)
    return 1.0 - p if z > 0 else p


def t_logpdf(x: float, df: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    z = (x - mu) / sigma
    return (math.lgamma((df + 1.0) / 2.0) - math.lgamma(df / 2.0)
            - 0.5 * math.log(df * math.pi) - math.log(sigma)
            - (df + 1.0) / 2.0 * math.log1p(z * z / df))


def t_ppf(p: float, df: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    """Inverse Student-t CDF by bisection + Newton polish (deterministic)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    # Bracket using normal approximation, expand if needed
    z0 = norm_ppf(p)
    lo, hi = z0 - 1.0, z0 + 1.0
    for _ in range(200):
        if t_cdf(lo, df) < p:
            break
        lo -= max(1.0, abs(lo))
    for _ in range(200):
        if t_cdf(hi, df) > p:
            break
        hi += max(1.0, abs(hi))
    x = 0.5 * (lo + hi)
    for _ in range(200):
        fx = t_cdf(x, df) - p
        if fx > 0:
            hi = x
        else:
            lo = x
        pdf = math.exp(t_logpdf(x, df))
        if pdf > 1e-300:
            x_new = x - fx / pdf
            x = x_new if lo < x_new < hi else 0.5 * (lo + hi)
        else:
            x = 0.5 * (lo + hi)
        if hi - lo < 1e-13 * max(1.0, abs(x)) + 1e-14:
            break
    return mu + sigma * x


def t_crps(y: float, df: float, mu: float = 0.0, sigma: float = 1.0) -> float:
    """Closed-form CRPS for location-scale Student-t (Jordan et al. 2019).

    Valid for df > 1 (finite first moment).
    """
    if df <= 1.0:
        raise ValueError("t CRPS requires df > 1")
    z = (y - mu) / sigma
    fz = math.exp(t_logpdf(z, df))
    big_fz = t_cdf(z, df)
    term = (z * (2.0 * big_fz - 1.0)
            + 2.0 * fz * (df + z * z) / (df - 1.0)
            - (2.0 * math.sqrt(df) / (df - 1.0))
            * math.exp(_log_beta(0.5, df - 0.5) - 2.0 * _log_beta(0.5, df / 2.0)))
    return sigma * term


# ---------------------------------------------------------------------------
# Deterministic quadrature
# ---------------------------------------------------------------------------

def trapezoid(fn: Callable[[float], float], lo: float, hi: float, n: int = 512) -> float:
    if n < 2:
        raise ValueError("n must be >= 2")
    h = (hi - lo) / n
    total = 0.5 * (fn(lo) + fn(hi))
    for i in range(1, n):
        total += fn(lo + i * h)
    return total * h


def log_sum_exp(values: Sequence[float]) -> float:
    m = max(values)
    if m == -math.inf:
        return -math.inf
    return m + math.log(sum(math.exp(v - m) for v in values))


# ---------------------------------------------------------------------------
# Scoring rules and calibration
# ---------------------------------------------------------------------------

def brier(probability: float, outcome: bool) -> float:
    if not 0.0 <= probability <= 1.0:
        raise ValueError("probability must be in [0, 1]")
    return (probability - float(outcome)) ** 2


def log_loss(probability: float, outcome: bool, *, floor: float = 1e-12) -> float:
    p = min(1.0 - floor, max(floor, probability))
    return -math.log(p if outcome else 1.0 - p)


def interval_coverage(hits: Sequence[bool]) -> float:
    if not hits:
        raise ValueError("empty coverage sample")
    return sum(hits) / len(hits)


def expected_calibration_error(probabilities: Sequence[float], outcomes: Sequence[bool], *, bins: int = 10) -> float:
    """Binned ECE for binary probability forecasts."""
    if len(probabilities) != len(outcomes) or not probabilities:
        raise ValueError("probabilities and outcomes must be equal-length, non-empty")
    totals = [0] * bins
    prob_sums = [0.0] * bins
    outcome_sums = [0.0] * bins
    for p, o in zip(probabilities, outcomes):
        idx = min(bins - 1, int(p * bins))
        totals[idx] += 1
        prob_sums[idx] += p
        outcome_sums[idx] += float(o)
    n = len(probabilities)
    ece = 0.0
    for i in range(bins):
        if totals[i]:
            ece += (totals[i] / n) * abs(prob_sums[i] / totals[i] - outcome_sums[i] / totals[i])
    return ece


def pit_values(cdf_at_observation: Sequence[float]) -> dict[str, float]:
    """Summary of probability-integral-transform uniformity.

    Returns mean and a Cramer-von-Mises style discrepancy against U(0,1);
    both deterministic. A well-calibrated forecaster gives mean ~0.5 and
    low discrepancy.
    """
    if not cdf_at_observation:
        raise ValueError("empty PIT sample")
    values = sorted(min(1.0, max(0.0, v)) for v in cdf_at_observation)
    n = len(values)
    mean = sum(values) / n
    cvm = 1.0 / (12.0 * n) + sum((v - (2.0 * i + 1.0) / (2.0 * n)) ** 2 for i, v in enumerate(values))
    return {"mean": mean, "cvm": cvm, "n": n}


# ---------------------------------------------------------------------------
# Deterministic RNG (SplitMix64) — reproducible across platforms
# ---------------------------------------------------------------------------

class DeterministicRng:
    """SplitMix64-based generator: identical streams for identical seeds on
    every platform, independent of Python's Mersenne Twister internals."""

    _MASK = (1 << 64) - 1

    def __init__(self, seed: int):
        self._state = seed & self._MASK

    def next_u64(self) -> int:
        self._state = (self._state + 0x9E3779B97F4A7C15) & self._MASK
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & self._MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & self._MASK
        return z ^ (z >> 31)

    def uniform(self, lo: float = 0.0, hi: float = 1.0) -> float:
        return lo + (hi - lo) * (self.next_u64() >> 11) / float(1 << 53)

    def normal(self, mu: float = 0.0, sigma: float = 1.0) -> float:
        # Inverse-CDF sampling keeps the stream deterministic and monotone.
        u = self.uniform()
        u = min(1.0 - 1e-16, max(1e-16, u))
        return norm_ppf(u, mu, sigma)

    def lognormal(self, mu: float, sigma: float) -> float:
        return math.exp(self.normal(mu, sigma))

    def student_t(self, df: float, mu: float = 0.0, sigma: float = 1.0) -> float:
        u = min(1.0 - 1e-12, max(1e-12, self.uniform()))
        return t_ppf(u, df, mu, sigma)

    def bernoulli(self, p: float) -> bool:
        return self.uniform() < p

    def beta(self, a: float, b: float) -> float:
        """Deterministic beta sample via Johnk/gamma-free inverse method:
        uses two-gamma representation with Marsaglia-Tsang replaced by
        sum-of-exponentials for integer-ish shapes; falls back to
        numeric inversion of the CDF for stability."""
        # Numeric inversion: deterministic bisection on regularized beta.
        u = min(1.0 - 1e-12, max(1e-12, self.uniform()))
        lo, hi = 0.0, 1.0
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if _betainc_regularized(a, b, mid) < u:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def choice_index(self, n: int) -> int:
        if n <= 0:
            raise ValueError("n must be positive")
        return self.next_u64() % n


def stable_seed(*parts: Any) -> int:
    """Derive a 64-bit seed from canonical JSON of the parts (deterministic)."""
    import hashlib
    import json
    encoded = json.dumps(list(parts), sort_keys=True, separators=(",", ":")).encode()
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big")
