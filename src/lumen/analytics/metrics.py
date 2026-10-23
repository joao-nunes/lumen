"""Descriptive metrics over daily series.

Every result carries the number of data points it is based on, and returns
`None` instead of a number when there is too little data (PROJECT.MD §7).
"""

from dataclasses import dataclass
from datetime import date, timedelta
from math import fsum

from lumen.analytics.series import DailySeries, DateRange, restrict

DEFAULT_MIN_POINTS = 3


@dataclass(frozen=True, slots=True)
class PeriodStat:
    mean: float | None
    n: int


@dataclass(frozen=True, slots=True)
class PeriodChange:
    current: PeriodStat
    previous: PeriodStat
    delta: float | None


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


def period_change(
    series: DailySeries,
    current: DateRange,
    previous: DateRange | None = None,
    min_points: int = DEFAULT_MIN_POINTS,
) -> PeriodChange:
    """Δ = mean(current) - mean(previous); previous defaults to the preceding equal-length range."""
    cur = period_stat(series, current, min_points)
    prev = period_stat(series, previous or current.previous(), min_points)
    delta = cur.mean - prev.mean if cur.mean is not None and prev.mean is not None else None
    return PeriodChange(current=cur, previous=prev, delta=delta)


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
