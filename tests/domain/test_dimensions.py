from datetime import date, timedelta

import pytest

from lumen.domain.dimensions import (
    CORE_DIMENSIONS,
    DIMENSIONS,
    ROTATING_DIMENSIONS,
    SCALE_MAX,
    SCALE_MIN,
    Dimension,
    InvalidScoreError,
    Polarity,
    dimensions_for,
    rotating_dimensions_for,
    validate_score,
)


def test_every_dimension_has_a_spec_with_one_anchor_per_scale_point() -> None:
    assert set(DIMENSIONS) == set(Dimension)
    for spec in DIMENSIONS.values():
        assert len(spec.anchors) == SCALE_MAX - SCALE_MIN + 1


def test_core_dimensions_are_mood_energy_stress() -> None:
    assert set(CORE_DIMENSIONS) == {Dimension.MOOD, Dimension.ENERGY, Dimension.STRESS}


def test_stress_is_the_only_dimension_where_higher_is_worse() -> None:
    worse = {d for d, s in DIMENSIONS.items() if s.polarity is Polarity.HIGHER_IS_WORSE}
    assert worse == {Dimension.STRESS}


def test_anchor_for_returns_the_matching_anchor() -> None:
    mood = DIMENSIONS[Dimension.MOOD]
    assert mood.anchor_for(1).label == "Very low"
    assert mood.anchor_for(5).label == "Very good"


@pytest.mark.parametrize("value", [SCALE_MIN, 3, SCALE_MAX])
def test_validate_score_accepts_values_in_scale(value: int) -> None:
    assert validate_score(value) == value


@pytest.mark.parametrize("value", [0, 6, -1, 2.5, True, "3"])
def test_validate_score_rejects_invalid_values(value: object) -> None:
    with pytest.raises(InvalidScoreError):
        validate_score(value)  # type: ignore[arg-type]


def test_rotation_is_deterministic() -> None:
    day = date(2026, 10, 23)
    assert rotating_dimensions_for(day) == rotating_dimensions_for(day)


def test_rotation_asks_every_rotating_dimension_within_a_few_days() -> None:
    start = date(2026, 1, 1)
    asked = {
        d
        for offset in range(len(ROTATING_DIMENSIONS))
        for d in rotating_dimensions_for(start + timedelta(days=offset))
    }
    assert asked == set(ROTATING_DIMENSIONS)


def test_rotation_has_no_duplicates_within_a_day() -> None:
    for offset in range(30):
        dims = rotating_dimensions_for(date(2026, 1, 1) + timedelta(days=offset), per_day=3)
        assert len(set(dims)) == 3


def test_dimensions_for_always_includes_core() -> None:
    dims = dimensions_for(date(2026, 3, 14))
    assert dims[: len(CORE_DIMENSIONS)] == CORE_DIMENSIONS
    assert len(dims) == len(CORE_DIMENSIONS) + 2


def test_rotation_rejects_out_of_range_per_day() -> None:
    with pytest.raises(ValueError):
        rotating_dimensions_for(date(2026, 1, 1), per_day=len(ROTATING_DIMENSIONS) + 1)
