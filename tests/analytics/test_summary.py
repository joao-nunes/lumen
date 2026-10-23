from datetime import date, timedelta

import numpy as np

from lumen.analytics.direction import Direction, Outlook
from lumen.analytics.summary import summarize, summarize_all, summary_start
from lumen.domain.dimensions import Dimension
from lumen.domain.observation import Observation

END = date(2026, 10, 23)


def daily(dimension: Dimension, latent: np.ndarray) -> list[Observation]:
    start = END - timedelta(days=len(latent) - 1)
    values = np.clip(np.round(latent), 1, 5).astype(int)
    return [Observation(start + timedelta(days=i), dimension, int(v)) for i, v in enumerate(values)]


def test_summary_start_covers_both_windows() -> None:
    assert summary_start(END, change_days=28, trend_days=84) == END - timedelta(days=83)
    assert summary_start(END, change_days=60, trend_days=84) == END - timedelta(days=119)


def test_recent_rise_in_stress_is_a_worsening_change() -> None:
    latent = np.r_[np.full(28, 2.0), np.full(28, 4.0)] + np.random.default_rng(0).normal(0, 0.4, 56)
    summary = summarize(daily(Dimension.STRESS, latent), Dimension.STRESS, END)
    assert summary.change.direction is Direction.INCREASING
    assert summary.change_outlook is Outlook.WORSENING


def test_steady_twelve_week_decline_in_mood_is_a_worsening_trend() -> None:
    latent = np.linspace(4.0, 2.0, 84) + np.random.default_rng(1).normal(0, 0.4, 84)
    summary = summarize(daily(Dimension.MOOD, latent), Dimension.MOOD, END)
    assert summary.trend.direction is Direction.DECREASING
    assert summary.trend_outlook is Outlook.WORSENING


def test_dimensions_without_data_are_reported_as_unknown() -> None:
    summaries = summarize_all(daily(Dimension.STRESS, np.full(56, 3.0)), END)
    assert set(summaries) == set(Dimension)
    mood = summaries[Dimension.MOOD]
    assert (
        mood.change.direction,
        mood.trend.direction,
        mood.change_outlook,
        mood.trend_outlook,
        mood.change_coverage.days_with_data,
    ) == (
        Direction.INSUFFICIENT_DATA,
        Direction.INSUFFICIENT_DATA,
        Outlook.UNKNOWN,
        Outlook.UNKNOWN,
        0,
    )
