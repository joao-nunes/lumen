from datetime import date

from lumen.analytics.series import DateRange, daily_means
from lumen.domain.dimensions import Dimension
from lumen.domain.observation import Observation


def test_date_range_is_inclusive_and_knows_its_predecessor() -> None:
    week = DateRange.ending_on(date(2026, 1, 14), 7)
    assert week == DateRange(date(2026, 1, 8), date(2026, 1, 14))
    assert week.days == 7
    assert list(week)[-1] == date(2026, 1, 14)
    assert week.previous() == DateRange(date(2026, 1, 1), date(2026, 1, 7))


def test_daily_means_average_each_day_for_one_dimension_and_never_fill_gaps() -> None:
    obs = [
        Observation(date(2026, 1, 1), Dimension.MOOD, 2),
        Observation(date(2026, 1, 1), Dimension.MOOD, 4),
        Observation(date(2026, 1, 1), Dimension.STRESS, 5),
        Observation(date(2026, 1, 3), Dimension.MOOD, 5),
    ]
    assert daily_means(obs, Dimension.MOOD) == {date(2026, 1, 1): 3.0, date(2026, 1, 3): 5.0}
