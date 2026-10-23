from datetime import date, timedelta

import numpy as np

from lumen.analytics.direction import Direction, Outlook
from lumen.analytics.summary import summarize, summarize_all, summary_start
from lumen.domain.dimensions import Dimension
from lumen.domain.observation import Observation

END = date(2026, 10, 23)


def daily(dimension: Dimension, values: list[int], end: date = END) -> list[Observation]:
    start = end - timedelta(days=len(values) - 1)
    return [Observation(start + timedelta(days=i), dimension, v) for i, v in enumerate(values)]


def test_summary_start_covers_both_windows() -> None:
    assert summary_start(END, change_days=28, trend_days=84) == END - timedelta(days=83)
    assert summary_start(END, change_days=60, trend_days=84) == END - timedelta(days=119)


def test_windows_are_independent() -> None:
    summary = summarize([], Dimension.MOOD, END, change_days=14, trend_days=56)
    assert summary.change_period.days == 14
    assert summary.trend_period.days == 56
    assert summary.change_coverage.days_total == 14
    assert summary.trend_coverage.days_total == 56


def test_recent_rise_in_stress_is_a_worsening_change() -> None:
    rng = np.random.default_rng(0)
    values = [
        int(np.clip(round(v), 1, 5))
        for v in np.r_[np.full(28, 2.0), np.full(28, 4.0)] + rng.normal(0, 0.4, 56)
    ]
    summary = summarize(daily(Dimension.STRESS, values), Dimension.STRESS, END)
    assert summary.change.direction is Direction.INCREASING
    assert summary.change_outlook is Outlook.WORSENING


def test_steady_twelve_week_decline_in_mood_is_a_worsening_trend() -> None:
    rng = np.random.default_rng(1)
    latent = np.linspace(4.0, 2.0, 84) + rng.normal(0, 0.4, 84)
    values = [int(np.clip(round(v), 1, 5)) for v in latent]
    summary = summarize(daily(Dimension.MOOD, values), Dimension.MOOD, END)
    assert summary.trend.direction is Direction.DECREASING
    assert summary.trend_outlook is Outlook.WORSENING


def test_summarize_all_covers_every_dimension_and_reports_missing_data() -> None:
    summaries = summarize_all(daily(Dimension.STRESS, [3] * 56), END)
    assert set(summaries) == set(Dimension)
    mood = summaries[Dimension.MOOD]
    assert mood.change.direction is Direction.INSUFFICIENT_DATA
    assert mood.trend.direction is Direction.INSUFFICIENT_DATA
    assert mood.change_outlook is Outlook.UNKNOWN
    assert mood.change_coverage.days_with_data == 0
