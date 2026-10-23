from datetime import date, timedelta

from lumen.domain.dimensions import CORE_DIMENSIONS, ROTATING_DIMENSIONS, dimensions_for


def test_every_dimension_is_asked_within_two_days_and_core_ones_daily() -> None:
    day = date(2026, 3, 14)
    asked = [dimensions_for(day + timedelta(days=i)) for i in range(2)]
    for dims in asked:
        assert dims[: len(CORE_DIMENSIONS)] == CORE_DIMENSIONS
        assert len(set(dims)) == len(dims) == len(CORE_DIMENSIONS) + 2
    assert set(asked[0] + asked[1]) == set(CORE_DIMENSIONS + ROTATING_DIMENSIONS)
