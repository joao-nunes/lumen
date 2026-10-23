"""Trend estimation with uncertainty.

Methodology (PROJECT.MD §7):

1. Fit an ordinary least-squares slope of daily values against day number,
   using only days that have data.
2. Correct for autocorrelation. Wellbeing is "sticky" (a bad day tends to be
   followed by another), so consecutive residuals are not independent and a
   naive confidence interval is too narrow. Following Santer et al. (2000),
   the sample size is replaced by an effective sample size
   n_eff = n (1 - r1) / (1 + r1), where r1 is the lag-1 autocorrelation of
   the residuals, and the standard error and degrees of freedom use n_eff.
   Consecutive observations are treated as adjacent even across missing
   days, which is an approximation.
3. Classify, using the confidence interval and a practical threshold:
   - INCREASING / DECREASING: the interval excludes zero *and* the slope is
     at least `flat_threshold_per_week` in magnitude.
   - FLAT: the whole interval lies within ±`flat_threshold_per_week`, i.e. we
     are confident any change is too small to matter.
   - UNCLEAR: anything else; the data cannot distinguish a trend from noise.

Slopes are reported per week, because a per-day slope on a 1-5 scale is too
small to read.
"""

from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from math import fsum, sqrt

from scipy.stats import t as student_t

from lumen.analytics.series import DailySeries, DateRange, restrict
from lumen.domain.dimensions import Polarity

DEFAULT_TREND_MIN_POINTS = 7
DEFAULT_FLAT_THRESHOLD_PER_WEEK = 0.1
DEFAULT_CONFIDENCE = 0.95
# Below this effective sample size the interval is too unreliable to report.
MIN_EFFECTIVE_POINTS = 4.0


class TrendDirection(StrEnum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    FLAT = "flat"
    UNCLEAR = "unclear"
    INSUFFICIENT_DATA = "insufficient_data"


class Outlook(StrEnum):
    """Direction interpreted through the dimension's polarity."""

    IMPROVING = "improving"
    WORSENING = "worsening"
    STABLE = "stable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Trend:
    slope_per_week: float | None
    ci_low_per_week: float | None
    ci_high_per_week: float | None
    direction: TrendDirection
    n: int
    n_effective: float | None


@dataclass(frozen=True, slots=True)
class SlopeFit:
    slope: float
    intercept: float
    residuals: list[float]
    sxx: float


def ols_fit(xs: list[float], ys: list[float]) -> SlopeFit:
    if len(xs) != len(ys):
        raise ValueError("xs and ys must have the same length")
    if len(xs) < 2:
        raise ValueError("At least two points are needed for a slope")
    mean_x = fsum(xs) / len(xs)
    mean_y = fsum(ys) / len(ys)
    sxx = fsum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        raise ValueError("All x values are identical; slope is undefined")
    sxy = fsum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys, strict=True)]
    return SlopeFit(slope=slope, intercept=intercept, residuals=residuals, sxx=sxx)


def ols_slope(xs: list[float], ys: list[float]) -> float:
    return ols_fit(xs, ys).slope


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


def trend(
    series: DailySeries,
    period: DateRange,
    min_points: int = DEFAULT_TREND_MIN_POINTS,
    flat_threshold_per_week: float = DEFAULT_FLAT_THRESHOLD_PER_WEEK,
    confidence: float = DEFAULT_CONFIDENCE,
) -> Trend:
    if not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    points = restrict(series, period)
    n = len(points)
    if n < max(min_points, 3):
        return Trend(None, None, None, TrendDirection.INSUFFICIENT_DATA, n, None)

    xs = [float((day - period.start).days) for day in points]
    fit = ols_fit(xs, list(points.values()))
    slope = fit.slope * 7
    n_eff = effective_sample_size(n, lag1_autocorrelation(fit.residuals))
    if n_eff < MIN_EFFECTIVE_POINTS:
        return Trend(slope, None, None, TrendDirection.INSUFFICIENT_DATA, n, n_eff)

    residual_variance = fsum(r * r for r in fit.residuals) / (n_eff - 2)
    std_error = sqrt(residual_variance / fit.sxx) * 7
    margin = float(student_t.ppf(0.5 + confidence / 2, n_eff - 2)) * std_error
    low, high = slope - margin, slope + margin

    if (low > 0 or high < 0) and abs(slope) >= flat_threshold_per_week:
        direction = TrendDirection.INCREASING if slope > 0 else TrendDirection.DECREASING
    elif -flat_threshold_per_week < low and high < flat_threshold_per_week:
        direction = TrendDirection.FLAT
    else:
        direction = TrendDirection.UNCLEAR
    return Trend(slope, low, high, direction, n, n_eff)


def outlook(direction: TrendDirection, polarity: Polarity) -> Outlook:
    if direction in (TrendDirection.INSUFFICIENT_DATA, TrendDirection.UNCLEAR):
        return Outlook.UNKNOWN
    if direction is TrendDirection.FLAT:
        return Outlook.STABLE
    rising = direction is TrendDirection.INCREASING
    if rising == (polarity is Polarity.HIGHER_IS_BETTER):
        return Outlook.IMPROVING
    return Outlook.WORSENING
