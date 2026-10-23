"""Per-dimension summary: the numbers behind the wellbeing overview (PROJECT.MD §7).

Two questions use two windows:

- "How am I doing lately?" compares the last `change_days` with the
  `change_days` before them. Shorter windows respond quickly, and a
  difference in means is detectable with less data than a slope.
- "Where am I heading?" fits a trend over the last `trend_days`. Wellbeing
  changes slowly relative to day-to-day noise, so a slope needs a long
  window to be distinguishable from noise.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from lumen.analytics.direction import Outlook, outlook
from lumen.analytics.metrics import Coverage, PeriodChange, coverage, period_change
from lumen.analytics.series import DateRange, daily_means
from lumen.analytics.trends import Trend, trend
from lumen.domain.dimensions import DIMENSIONS, Dimension
from lumen.domain.observation import Observation

DEFAULT_CHANGE_WINDOW_DAYS = 28
DEFAULT_TREND_WINDOW_DAYS = 84


@dataclass(frozen=True, slots=True)
class DimensionSummary:
    dimension: Dimension
    change_period: DateRange
    change: PeriodChange
    change_outlook: Outlook
    change_coverage: Coverage
    trend_period: DateRange
    trend: Trend
    trend_outlook: Outlook
    trend_coverage: Coverage


def summary_start(
    end: date,
    change_days: int = DEFAULT_CHANGE_WINDOW_DAYS,
    trend_days: int = DEFAULT_TREND_WINDOW_DAYS,
) -> date:
    """Earliest day of data a summary ending on `end` needs; use it to query observations."""
    change_period = DateRange.ending_on(end, change_days)
    return min(change_period.previous().start, DateRange.ending_on(end, trend_days).start)


def summarize(
    observations: Iterable[Observation],
    dimension: Dimension,
    end: date,
    change_days: int = DEFAULT_CHANGE_WINDOW_DAYS,
    trend_days: int = DEFAULT_TREND_WINDOW_DAYS,
) -> DimensionSummary:
    series = daily_means(observations, dimension)
    polarity = DIMENSIONS[dimension].polarity
    change_period = DateRange.ending_on(end, change_days)
    trend_period = DateRange.ending_on(end, trend_days)
    change = period_change(series, change_period)
    t = trend(series, trend_period)
    return DimensionSummary(
        dimension=dimension,
        change_period=change_period,
        change=change,
        change_outlook=outlook(change.direction, polarity),
        change_coverage=coverage(series, change_period),
        trend_period=trend_period,
        trend=t,
        trend_outlook=outlook(t.direction, polarity),
        trend_coverage=coverage(series, trend_period),
    )


def summarize_all(
    observations: Iterable[Observation],
    end: date,
    change_days: int = DEFAULT_CHANGE_WINDOW_DAYS,
    trend_days: int = DEFAULT_TREND_WINDOW_DAYS,
) -> dict[Dimension, DimensionSummary]:
    obs = list(observations)
    return {d: summarize(obs, d, end, change_days, trend_days) for d in Dimension}
