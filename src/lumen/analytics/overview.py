"""Everything the overview screen shows for each dimension (spec 002 §2.5).

The summary answers "how am I doing lately" and "where am I heading"; the
daily means and 7-day rolling mean over the trend window are what gets drawn.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from lumen.analytics.metrics import PeriodStat, rolling_mean
from lumen.analytics.series import DailySeries, daily_means, restrict
from lumen.analytics.summary import DimensionSummary, summarize_all, summary_start
from lumen.domain.dimensions import DIMENSIONS, Dimension
from lumen.domain.observation import Observation

ROLLING_WINDOW_DAYS = 7


@dataclass(frozen=True, slots=True)
class DimensionOverview:
    summary: DimensionSummary
    # Days with data inside the trend window.
    daily: DailySeries
    # 7-day rolling mean for every day of the trend window (mean is None
    # where the window has too little data).
    rolling: dict[date, PeriodStat]


def overview_start(end: date) -> date:
    """Earliest day of data an overview ending on `end` needs; use it to query observations.

    The rolling mean on the first day of the trend window looks back
    ROLLING_WINDOW_DAYS - 1 further days.
    """
    return summary_start(end) - timedelta(days=ROLLING_WINDOW_DAYS - 1)


def overview(observations: Iterable[Observation], end: date) -> dict[Dimension, DimensionOverview]:
    """Per dimension, in DIMENSIONS order."""
    obs = list(observations)
    summaries = summarize_all(obs, end)
    result: dict[Dimension, DimensionOverview] = {}
    for dimension in DIMENSIONS:
        summary = summaries[dimension]
        series = daily_means(obs, dimension)
        result[dimension] = DimensionOverview(
            summary=summary,
            daily=restrict(series, summary.trend_period),
            rolling=rolling_mean(series, summary.trend_period, ROLLING_WINDOW_DAYS),
        )
    return result
