from datetime import date, timedelta

import pytest

from lumen.domain.dimensions import (
    CORE_DIMENSIONS,
    ROTATING_DIMENSIONS,
    InvalidScoreError,
    dimensions_for,
    rotating_dimensions_for,
    validate_score,
)


def test_validate_score_accepts_only_integers_on_the_scale() -> None:
    assert validate_score(1) == 1
    assert validate_score(5) == 5
    for invalid in (0, 6, 2.5, True):
        with pytest.raises(InvalidScoreError):
            validate_score(invalid)  # type: ignore[arg-type]


def test_rotation_asks_every_rotating_dimension_regularly_without_repeats() -> None:
    start = date(2026, 1, 1)
    days = [rotating_dimensions_for(start + timedelta(days=i)) for i in range(4)]
    assert all(len(set(d)) == len(d) for d in days)
    assert {dim for day in days for dim in day} == set(ROTATING_DIMENSIONS)


def test_each_day_asks_all_core_dimensions_plus_rotating_ones() -> None:
    dims = dimensions_for(date(2026, 3, 14))
    assert dims[: len(CORE_DIMENSIONS)] == CORE_DIMENSIONS
    assert len(dims) == len(CORE_DIMENSIONS) + 2
