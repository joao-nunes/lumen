from datetime import UTC, date, datetime

import pytest

from lumen.domain.checkin import Checkin, InvalidTagError
from lumen.domain.dimensions import Dimension, InvalidScoreError

NOW = datetime(2026, 10, 23, 21, 0, tzinfo=UTC)
DAY = date(2026, 10, 23)


def test_checkin_accepts_scale_limits_and_normalizes_tags() -> None:
    checkin = Checkin(
        NOW,
        DAY,
        {Dimension.MOOD: 1, Dimension.STRESS: 5},
        frozenset({" Time outdoors", "caffeine-late"}),
    )
    assert checkin.tags == frozenset({"time_outdoors", "caffeine_late"})


@pytest.mark.parametrize(
    ("scores", "tags", "error"),
    [
        ({Dimension.MOOD: 0}, (), InvalidScoreError),
        ({Dimension.MOOD: 6}, (), InvalidScoreError),
        ({Dimension.MOOD: True}, (), InvalidScoreError),  # bool is an int subclass
        ({Dimension.MOOD: 3}, ("",), InvalidTagError),
        ({Dimension.MOOD: 3}, ("x" * 41,), InvalidTagError),
        ({Dimension.MOOD: 3}, ("café",), InvalidTagError),
    ],
)
def test_checkin_rejects_invalid_scores_and_tags(
    scores: dict[Dimension, int], tags: tuple[str, ...], error: type[Exception]
) -> None:
    with pytest.raises(error):
        Checkin(NOW, DAY, scores, frozenset(tags))


def test_checkin_requires_timezone_aware_timestamp() -> None:
    # A naive timestamp would be stored in the database server's timezone.
    with pytest.raises(ValueError, match="timezone-aware"):
        Checkin(datetime(2026, 10, 23, 21, 0), DAY, {Dimension.MOOD: 3})  # noqa: DTZ001
