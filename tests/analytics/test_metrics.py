from datetime import date, timedelta

import pytest

from lumen.analytics.metrics import coverage, period_change, period_stat, rolling_mean, weekly_means
from lumen.analytics.series import DailySeries, DateRange

START = date(2026, 1, 5)  # a Monday


def series_from(values: list[float | None], start: date = START) -> DailySeries:
    return {start + timedelta(days=i): v for i, v in enumerate(values) if v is not None}


def test_period_stat_mean_and_n() -> None:
    s = series_from([1, 2, 3, 4, 5])
    stat = period_stat(s, DateRange.ending_on(START + timedelta(days=4), 5))
    assert stat.mean == pytest.approx(3.0)
    assert stat.n == 5


def test_period_stat_returns_none_below_min_points() -> None:
    s = series_from([4, None, None, 2])
    stat = period_stat(s, DateRange.ending_on(START + timedelta(days=3), 4), min_points=3)
    assert stat.mean is None
    assert stat.n == 2


def test_period_change_matches_spec_example() -> None:
    # Previous week averages 4.0, current week averages 3.0 -> delta -1.0
    s = series_from([4] * 7 + [3] * 7)
    change = period_change(s, DateRange.ending_on(START + timedelta(days=13), 7))
    assert change.previous.mean == pytest.approx(4.0)
    assert change.current.mean == pytest.approx(3.0)
    assert change.delta == pytest.approx(-1.0)


def test_period_change_delta_is_none_when_a_period_lacks_data() -> None:
    s = series_from([None] * 7 + [3] * 7)
    change = period_change(s, DateRange.ending_on(START + timedelta(days=13), 7))
    assert change.delta is None
    assert change.previous.n == 0


def test_rolling_mean_uses_calendar_day_window() -> None:
    s = series_from([1, 2, 3, None, 5])
    result = rolling_mean(
        s, DateRange(START, START + timedelta(days=4)), window_days=3, min_points=2
    )
    assert result[START].mean is None  # only 1 point in window
    assert result[START + timedelta(days=1)].mean == pytest.approx(1.5)
    assert result[START + timedelta(days=2)].mean == pytest.approx(2.0)
    # Window [day2, day4] has values 2, 3 (day 3 missing) -> n=2, not stretched back
    assert result[START + timedelta(days=3)].n == 2
    assert result[START + timedelta(days=3)].mean == pytest.approx(2.5)
    assert result[START + timedelta(days=4)].mean == pytest.approx(4.0)


def test_rolling_mean_rejects_invalid_window() -> None:
    with pytest.raises(ValueError):
        rolling_mean({}, DateRange(START, START), window_days=0)


def test_weekly_means_keyed_by_monday_including_partial_weeks() -> None:
    s = series_from([4] * 7 + [2] * 7)
    period = DateRange(START + timedelta(days=2), START + timedelta(days=10))  # Wed -> next Thu
    weeks = weekly_means(s, period, min_points=1)
    assert list(weeks) == [START, START + timedelta(days=7)]
    assert weeks[START].n == 5
    assert weeks[START].mean == pytest.approx(4.0)
    assert weeks[START + timedelta(days=7)].n == 4
    assert weeks[START + timedelta(days=7)].mean == pytest.approx(2.0)


def test_coverage() -> None:
    s = series_from([3, None, 3, None, None, 3, 3])
    cov = coverage(s, DateRange(START, START + timedelta(days=6)))
    assert (cov.days_with_data, cov.days_total) == (4, 7)
    assert cov.ratio == pytest.approx(4 / 7)
