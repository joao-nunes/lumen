"""Statistical helpers shared by trends and period comparisons.

Day-to-day wellbeing is autocorrelated ("sticky"): a bad day tends to be
followed by another. Treating each day as independent overstates how much
information the data holds, producing intervals that are too narrow. Every
interval in this package therefore uses an effective sample size based on
lag-1 autocorrelation (Santer et al., 2000):

    n_eff = n (1 - r1) / (1 + r1)

Because r1 estimated from a short series is biased towards zero (which
would make intervals too narrow), it is bias-corrected first using the
approximation E[r1] ~ rho - (1 + 3 rho) / n (Kendall; Marriott & Pope),
i.e. rho ~ (n r1 + 1) / (n - 3).

Consecutive observations are treated as adjacent even across missing days,
which is an approximation.

Calibration is checked by simulation in tests/analytics/test_calibration.py:
95% intervals reach ~94-96% coverage for lag-1 autocorrelation up to 0.5,
and are somewhat too narrow (~89-93%) for very sticky data (0.7).
"""

from itertools import pairwise
from math import fsum

from scipy.stats import t as student_t

DEFAULT_CONFIDENCE = 0.95
# Below this effective sample size an interval is too unreliable to report.
MIN_EFFECTIVE_POINTS = 4.0


def lag1_autocorrelation(values: list[float]) -> float:
    """Lag-1 autocorrelation; 0 when undefined (fewer than 2 values or no variance)."""
    if len(values) < 2:
        return 0.0
    mean = fsum(values) / len(values)
    deviations = [v - mean for v in values]
    denominator = fsum(d * d for d in deviations)
    if denominator == 0:
        return 0.0
    return fsum(a * b for a, b in pairwise(deviations)) / denominator


def effective_sample_size(n: int, r1: float) -> float:
    # Negative autocorrelation would *inflate* n_eff; clamp to 0 to stay conservative.
    r1 = min(max(r1, 0.0), 0.99)
    return n * (1 - r1) / (1 + r1)


def bias_corrected_lag1(values: list[float]) -> float:
    n = len(values)
    r1 = lag1_autocorrelation(values)
    return (n * r1 + 1) / (n - 3) if n > 3 else r1


def effective_sample_size_of(values: list[float]) -> float:
    """Effective sample size of a sequence, from its bias-corrected lag-1 autocorrelation."""
    return effective_sample_size(len(values), bias_corrected_lag1(values))


def t_critical(confidence: float, dof: float) -> float:
    """Two-sided critical value of Student's t distribution."""
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    if dof <= 0:
        raise ValueError("degrees of freedom must be positive")
    return float(student_t.ppf(0.5 + confidence / 2, dof))
