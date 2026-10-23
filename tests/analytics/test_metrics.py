from datetime import date, timedelta

import pytest

from lumen.analytics.direction import Direction
from lumen.analytics.metrics import period_change, rolling_mean, weekly_means
from lumen.analytics.series import DailySeries, DateRange

START = date(2026, 1, 5)  # a Monday


def series_from(values: list[float | None]) -> DailySeries:
    return {START + timedelta(days=i): v for i, v in enumerate(values) if v is not None}


def test_period_change_between_constant_periods_is_exact() -> None:
    change = period_change(
        series_from([4] * 7 + [3] * 7), DateRange.ending_on(START + timedelta(days=13), 7)
    )
    assert (change.delta, change.ci_low, change.ci_high, change.direction) == (
        pytest.approx(-1.0),
        pytest.approx(-1.0),
        pytest.approx(-1.0),
        Direction.DECREASING,
    )


def test_period_change_without_data_in_one_period_is_insufficient() -> None:
    change = period_change(
        series_from([None] * 7 + [3] * 7), DateRange.ending_on(START + timedelta(days=13), 7)
    )
    assert (change.previous.n, change.delta, change.direction) == (
        0,
        None,
        Direction.INSUFFICIENT_DATA,
    )


def test_rolling_mean_window_is_calendar_days_so_gaps_shrink_n() -> None:
    result = rolling_mean(
        series_from([1, 2, 3, None, 5]),
        DateRange(START, START + timedelta(days=4)),
        window_days=3,
        min_points=2,
    )
    assert result[START].mean is None
    assert result[START + timedelta(days=3)].n == 2
    assert result[START + timedelta(days=3)].mean == pytest.approx(2.5)


def test_weekly_means_are_keyed_by_monday_and_clip_partial_weeks() -> None:
    period = DateRange(START + timedelta(days=2), START + timedelta(days=10))  # Wed -> next Thu
    weeks = weekly_means(series_from([4] * 7 + [2] * 7), period, min_points=1)
    assert list(weeks) == [START, START + timedelta(days=7)]
    assert (weeks[START].n, weeks[START].mean) == (5, pytest.approx(4.0))
    assert (weeks[START + timedelta(days=7)].n, weeks[START + timedelta(days=7)].mean) == (
        4,
        pytest.approx(2.0),
    )
