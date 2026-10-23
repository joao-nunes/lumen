from datetime import UTC, date, datetime

import pytest

from lumen.domain.checkin import Checkin, InvalidTagError, normalize_tag
from lumen.domain.dimensions import Dimension, InvalidScoreError

NOW = datetime(2026, 10, 23, 21, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("exercise", "exercise"),
        ("Time outdoors", "time_outdoors"),
        (" caffeine-late ", "caffeine_late"),
    ],
)
def test_normalize_tag(raw: str, expected: str) -> None:
    assert normalize_tag(raw) == expected


@pytest.mark.parametrize("raw", ["", "1st", "café", "x" * 41, "drop table;"])
def test_normalize_tag_rejects_invalid(raw: str) -> None:
    with pytest.raises(InvalidTagError):
        normalize_tag(raw)


def test_checkin_normalizes_tags() -> None:
    checkin = Checkin(NOW, date(2026, 10, 23), {Dimension.MOOD: 3}, frozenset({"Time outdoors"}))
    assert checkin.tags == frozenset({"time_outdoors"})


def test_checkin_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        Checkin(datetime(2026, 10, 23, 21, 0), date(2026, 10, 23), {Dimension.MOOD: 3})  # noqa: DTZ001


def test_checkin_requires_at_least_one_score() -> None:
    with pytest.raises(ValueError, match="at least one score"):
        Checkin(NOW, date(2026, 10, 23), {})


def test_checkin_rejects_out_of_scale_scores() -> None:
    with pytest.raises(InvalidScoreError):
        Checkin(NOW, date(2026, 10, 23), {Dimension.MOOD: 7})
