from datetime import date

from lumen.analytics.series import daily_means
from lumen.domain.dimensions import Dimension
from lumen.domain.observation import Observation


def test_daily_means_average_same_day_checkins_per_dimension_without_filling_gaps() -> None:
    obs = [
        Observation(date(2026, 1, 1), Dimension.MOOD, 2),
        Observation(date(2026, 1, 1), Dimension.MOOD, 4),
        Observation(date(2026, 1, 1), Dimension.STRESS, 5),
        Observation(date(2026, 1, 3), Dimension.MOOD, 5),
    ]
    assert daily_means(obs, Dimension.MOOD) == {date(2026, 1, 1): 3.0, date(2026, 1, 3): 5.0}
