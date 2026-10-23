from datetime import date

import pytest

from lumen.analytics.series import DateRange, daily_means, restrict
from lumen.domain.dimensions import Dimension
from lumen.domain.observation import Observation


def test_date_range_is_inclusive() -> None:
    r = DateRange(date(2026, 1, 1), date(2026, 1, 7))
    assert r.days == 7
    days = list(r)
    assert days[0] == date(2026, 1, 1)
    assert days[-1] == date(2026, 1, 7)
    assert date(2026, 1, 7) in r
    assert date(2026, 1, 8) not in r


def test_date_range_rejects_reversed_bounds() -> None:
    with pytest.raises(ValueError):
        DateRange(date(2026, 1, 2), date(2026, 1, 1))


def test_ending_on_and_previous() -> None:
    week = DateRange.ending_on(date(2026, 1, 14), 7)
    assert week == DateRange(date(2026, 1, 8), date(2026, 1, 14))
    assert week.previous() == DateRange(date(2026, 1, 1), date(2026, 1, 7))


def test_daily_means_averages_multiple_checkins_on_one_day_and_filters_dimension() -> None:
    obs = [
        Observation(date(2026, 1, 1), Dimension.MOOD, 2),
        Observation(date(2026, 1, 1), Dimension.MOOD, 4),
        Observation(date(2026, 1, 1), Dimension.STRESS, 5),
        Observation(date(2026, 1, 3), Dimension.MOOD, 5),
    ]
    assert daily_means(obs, Dimension.MOOD) == {date(2026, 1, 1): 3.0, date(2026, 1, 3): 5.0}


def test_daily_means_leaves_missing_days_absent() -> None:
    obs = [
        Observation(date(2026, 1, 1), Dimension.MOOD, 3),
        Observation(date(2026, 1, 3), Dimension.MOOD, 3),
    ]
    assert date(2026, 1, 2) not in daily_means(obs, Dimension.MOOD)


def test_restrict() -> None:
    series = {date(2026, 1, d): float(d) for d in range(1, 11)}
    assert list(restrict(series, DateRange(date(2026, 1, 3), date(2026, 1, 4)))) == [
        date(2026, 1, 3),
        date(2026, 1, 4),
    ]
