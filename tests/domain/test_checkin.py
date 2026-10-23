from datetime import UTC, date, datetime

import pytest

from lumen.domain.checkin import Checkin, InvalidTagError, normalize_tag
from lumen.domain.dimensions import Dimension

NOW = datetime(2026, 10, 23, 21, 0, tzinfo=UTC)
DAY = date(2026, 10, 23)


def test_tags_are_normalized_to_snake_case() -> None:
    assert normalize_tag(" Time outdoors ") == "time_outdoors"
    assert normalize_tag("caffeine-late") == "caffeine_late"


def test_invalid_tags_are_rejected() -> None:
    for invalid in ("", "1st", "café", "x" * 41):
        with pytest.raises(InvalidTagError):
            normalize_tag(invalid)


def test_checkin_normalizes_its_tags() -> None:
    checkin = Checkin(NOW, DAY, {Dimension.MOOD: 3}, frozenset({"Time outdoors"}))
    assert checkin.tags == frozenset({"time_outdoors"})


def test_checkin_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Checkin(datetime(2026, 10, 23, 21, 0), DAY, {Dimension.MOOD: 3})  # noqa: DTZ001


def test_checkin_requires_at_least_one_score() -> None:
    with pytest.raises(ValueError, match="at least one score"):
        Checkin(NOW, DAY, {})
