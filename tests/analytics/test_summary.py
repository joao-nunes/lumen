from datetime import date, timedelta

from lumen.analytics.series import DateRange
from lumen.analytics.summary import summarize, summarize_all
from lumen.analytics.trends import Outlook, TrendDirection
from lumen.domain.dimensions import Dimension
from lumen.domain.observation import Observation

START = date(2026, 1, 1)


def rising_stress(days: int) -> list[Observation]:
    return [
        Observation(START + timedelta(days=i), Dimension.STRESS, 1 + i * 4 // (days - 1))
        for i in range(days)
    ]


def test_rising_stress_is_reported_as_worsening() -> None:
    obs = rising_stress(28)
    summary = summarize(obs, Dimension.STRESS, DateRange.ending_on(START + timedelta(days=27), 14))
    assert summary.trend.direction is TrendDirection.INCREASING
    assert summary.outlook is Outlook.WORSENING
    assert summary.change.delta is not None and summary.change.delta > 0
    assert summary.coverage.days_with_data == 14


def test_summarize_all_covers_every_dimension_and_reports_missing_data() -> None:
    period = DateRange.ending_on(START + timedelta(days=27), 14)
    summaries = summarize_all(rising_stress(28), period)
    assert set(summaries) == set(Dimension)
    mood = summaries[Dimension.MOOD]
    assert mood.outlook is Outlook.UNKNOWN
    assert mood.change.delta is None
    assert mood.coverage.days_with_data == 0
