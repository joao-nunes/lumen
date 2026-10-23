"""Descriptive metrics over daily series.

Every result carries the number of data points it is based on, and returns
`None` instead of a number when there is too little data (PROJECT.MD §7).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from math import fsum, sqrt

from lumen.analytics.direction import Direction, classify
from lumen.analytics.inference import (
    DEFAULT_CONFIDENCE,
    MIN_EFFECTIVE_POINTS,
    effective_sample_size_of,
    t_critical,
)
from lumen.analytics.series import DailySeries, DateRange, restrict

DEFAULT_MIN_POINTS = 3
# Smallest difference between period means considered meaningful (provisional).
DEFAULT_CHANGE_THRESHOLD = 0.25


@dataclass(frozen=True, slots=True)
class PeriodStat:
    mean: float | None
    n: int


@dataclass(frozen=True, slots=True)
class PeriodChange:
    current: PeriodStat
    previous: PeriodStat
    delta: float | None
    ci_low: float | None
    ci_high: float | None
    direction: Direction


@dataclass(frozen=True, slots=True)
class Coverage:
    days_with_data: int
    days_total: int

    @property
    def ratio(self) -> float:
        return self.days_with_data / self.days_total


def period_stat(
    series: DailySeries, period: DateRange, min_points: int = DEFAULT_MIN_POINTS
) -> PeriodStat:
    values = list(restrict(series, period).values())
    n = len(values)
    return PeriodStat(mean=fsum(values) / n if n >= max(min_points, 1) else None, n=n)


@dataclass(frozen=True, slots=True)
class _MeanUncertainty:
    variance_of_mean: float
    n_effective: float


def _mean_uncertainty(values: list[float]) -> _MeanUncertainty:
    n = len(values)
    mean = fsum(values) / n
    sample_variance = fsum((v - mean) ** 2 for v in values) / (n - 1)
    n_eff = effective_sample_size_of(values)
    return _MeanUncertainty(variance_of_mean=sample_variance / n_eff, n_effective=n_eff)


def period_change(
    series: DailySeries,
    current: DateRange,
    previous: DateRange | None = None,
    min_points: int = DEFAULT_MIN_POINTS,
    threshold: float = DEFAULT_CHANGE_THRESHOLD,
    confidence: float = DEFAULT_CONFIDENCE,
) -> PeriodChange:
    """Δ = mean(current) - mean(previous), with a confidence interval.

    `previous` defaults to the preceding equal-length range. The interval is
    a Welch-style interval in which each period's variance and degrees of
    freedom use its autocorrelation-adjusted effective sample size.
    """
    previous = previous or current.previous()
    cur = period_stat(series, current, min_points)
    prev = period_stat(series, previous, min_points)
    if cur.mean is None or prev.mean is None:
        return PeriodChange(cur, prev, None, None, None, Direction.INSUFFICIENT_DATA)
    delta = cur.mean - prev.mean

    a = _mean_uncertainty(list(restrict(series, current).values()))
    b = _mean_uncertainty(list(restrict(series, previous).values()))
    if min(a.n_effective, b.n_effective) < MIN_EFFECTIVE_POINTS:
        return PeriodChange(cur, prev, delta, None, None, Direction.INSUFFICIENT_DATA)

    variance = a.variance_of_mean + b.variance_of_mean
    if variance == 0:
        # Both periods are perfectly constant: the difference is exact.
        low = high = delta
    else:
        # Welch-Satterthwaite degrees of freedom.
        dof = variance**2 / (
            a.variance_of_mean**2 / (a.n_effective - 1)
            + b.variance_of_mean**2 / (b.n_effective - 1)
        )
        margin = t_critical(confidence, dof) * sqrt(variance)
        low, high = delta - margin, delta + margin
    return PeriodChange(cur, prev, delta, low, high, classify(delta, low, high, threshold))


def rolling_mean(
    series: DailySeries,
    period: DateRange,
    window_days: int = 7,
    min_points: int = DEFAULT_MIN_POINTS,
) -> dict[date, PeriodStat]:
    """Trailing calendar-day rolling mean for each day in `period`.

    The window for day t is [t - window_days + 1, t]. It is defined in
    calendar days, not in data points, so gaps in tracking shrink `n` rather
    than silently stretching the window back in time.
    """
    if window_days < 1:
        raise ValueError("window_days must be at least 1")
    return {
        day: period_stat(series, DateRange.ending_on(day, window_days), min_points)
        for day in period
    }


def weekly_means(
    series: DailySeries, period: DateRange, min_points: int = DEFAULT_MIN_POINTS
) -> dict[date, PeriodStat]:
    """Mean per ISO week (Monday start), keyed by the week's Monday.

    Partial weeks at either end of `period` only include the days inside it.
    """
    result: dict[date, PeriodStat] = {}
    monday = period.start - timedelta(days=period.start.weekday())
    while monday <= period.end:
        week = DateRange(max(monday, period.start), min(monday + timedelta(days=6), period.end))
        result[monday] = period_stat(series, week, min_points)
        monday += timedelta(days=7)
    return result


def coverage(series: DailySeries, period: DateRange) -> Coverage:
    return Coverage(days_with_data=len(restrict(series, period)), days_total=period.days)
