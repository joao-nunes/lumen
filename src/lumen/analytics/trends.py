"""Trend estimation with uncertainty.

Methodology (PROJECT.MD §7): ordinary least-squares slope of daily values
against day number, using only days that have data. The confidence interval
uses an effective sample size computed from the lag-1 autocorrelation of
the residuals (see `inference`), and the result is classified with
`direction.classify`.

Slopes are reported per week, because a per-day slope on a 1-5 scale is too
small to read. Slow changes need long windows to be distinguishable from
noise, hence the 12-week default window used by `summary`.
"""

from dataclasses import dataclass
from math import fsum, sqrt

from lumen.analytics.direction import Direction, classify
from lumen.analytics.inference import (
    DEFAULT_CONFIDENCE,
    MIN_EFFECTIVE_POINTS,
    effective_sample_size_of,
    t_critical,
)
from lumen.analytics.series import DailySeries, DateRange, restrict

DEFAULT_TREND_MIN_POINTS = 7
DEFAULT_FLAT_THRESHOLD_PER_WEEK = 0.1


@dataclass(frozen=True, slots=True)
class Trend:
    slope_per_week: float | None
    ci_low_per_week: float | None
    ci_high_per_week: float | None
    direction: Direction
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
        return Trend(None, None, None, Direction.INSUFFICIENT_DATA, n, None)

    xs = [float((day - period.start).days) for day in points]
    fit = ols_fit(xs, list(points.values()))
    slope = fit.slope * 7
    n_eff = effective_sample_size_of(fit.residuals)
    if n_eff < MIN_EFFECTIVE_POINTS:
        return Trend(slope, None, None, Direction.INSUFFICIENT_DATA, n, n_eff)

    residual_variance = fsum(r * r for r in fit.residuals) / (n_eff - 2)
    std_error = sqrt(residual_variance / fit.sxx) * 7
    margin = t_critical(confidence, n_eff - 2) * std_error
    low, high = slope - margin, slope + margin
    return Trend(slope, low, high, classify(slope, low, high, flat_threshold_per_week), n, n_eff)
