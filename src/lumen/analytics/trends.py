"""Trend estimation.

Methodology (provisional, PROJECT.MD §7/§18): ordinary least-squares slope of
daily values against day number, using only days that have data. The slope
is reported per week, because a per-day slope on a 1-5 scale is too small to
read. A trend is "flat" when its magnitude is below `flat_threshold_per_week`.
"""

from dataclasses import dataclass
from enum import StrEnum
from math import fsum

from lumen.analytics.series import DailySeries, DateRange, restrict
from lumen.domain.dimensions import Polarity

DEFAULT_TREND_MIN_POINTS = 7
DEFAULT_FLAT_THRESHOLD_PER_WEEK = 0.1


class TrendDirection(StrEnum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    FLAT = "flat"
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
    direction: TrendDirection
    n: int


def ols_slope(xs: list[float], ys: list[float]) -> float:
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
    return sxy / sxx


def trend(
    series: DailySeries,
    period: DateRange,
    min_points: int = DEFAULT_TREND_MIN_POINTS,
    flat_threshold_per_week: float = DEFAULT_FLAT_THRESHOLD_PER_WEEK,
) -> Trend:
    points = restrict(series, period)
    n = len(points)
    if n < max(min_points, 2):
        return Trend(slope_per_week=None, direction=TrendDirection.INSUFFICIENT_DATA, n=n)

    xs = [float((day - period.start).days) for day in points]
    slope = ols_slope(xs, list(points.values())) * 7

    if abs(slope) < flat_threshold_per_week:
        direction = TrendDirection.FLAT
    elif slope > 0:
        direction = TrendDirection.INCREASING
    else:
        direction = TrendDirection.DECREASING
    return Trend(slope_per_week=slope, direction=direction, n=n)


def outlook(direction: TrendDirection, polarity: Polarity) -> Outlook:
    if direction is TrendDirection.INSUFFICIENT_DATA:
        return Outlook.UNKNOWN
    if direction is TrendDirection.FLAT:
        return Outlook.STABLE
    rising = direction is TrendDirection.INCREASING
    if rising == (polarity is Polarity.HIGHER_IS_BETTER):
        return Outlook.IMPROVING
    return Outlook.WORSENING
