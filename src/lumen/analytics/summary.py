"""Per-dimension summary: the numbers behind the wellbeing overview (PROJECT.MD §7)."""

from collections.abc import Iterable
from dataclasses import dataclass

from lumen.analytics.metrics import Coverage, PeriodChange, coverage, period_change
from lumen.analytics.series import DateRange, daily_means
from lumen.analytics.trends import Outlook, Trend, outlook, trend
from lumen.domain.dimensions import DIMENSIONS, Dimension
from lumen.domain.observation import Observation


@dataclass(frozen=True, slots=True)
class DimensionSummary:
    dimension: Dimension
    period: DateRange
    change: PeriodChange
    trend: Trend
    outlook: Outlook
    coverage: Coverage


def summarize(
    observations: Iterable[Observation], dimension: Dimension, period: DateRange
) -> DimensionSummary:
    series = daily_means(observations, dimension)
    t = trend(series, period)
    return DimensionSummary(
        dimension=dimension,
        period=period,
        change=period_change(series, period),
        trend=t,
        outlook=outlook(t.direction, DIMENSIONS[dimension].polarity),
        coverage=coverage(series, period),
    )


def summarize_all(
    observations: Iterable[Observation], period: DateRange
) -> dict[Dimension, DimensionSummary]:
    obs = list(observations)
    return {dimension: summarize(obs, dimension, period) for dimension in Dimension}
