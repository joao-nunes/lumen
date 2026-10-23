from datetime import date, timedelta

import pytest

from lumen.analytics.series import DateRange
from lumen.analytics.trends import Outlook, TrendDirection, ols_slope, outlook, trend
from lumen.domain.dimensions import Polarity

START = date(2026, 1, 1)
PERIOD = DateRange(START, START + timedelta(days=27))


def test_ols_slope_exact_line() -> None:
    assert ols_slope([0, 1, 2, 3], [1, 3, 5, 7]) == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("xs", "ys"), [([1.0], [1.0]), ([1.0, 1.0], [1.0, 2.0]), ([1.0, 2.0], [1.0])]
)
def test_ols_slope_rejects_degenerate_input(xs: list[float], ys: list[float]) -> None:
    with pytest.raises(ValueError):
        ols_slope(xs, ys)


def test_trend_matches_spec_example_of_decreasing_weekly_mood() -> None:
    # Week 1: 4.0 ... Week 4: 2.5 -> -0.5 per week
    values = [4.0] * 7 + [3.5] * 7 + [3.0] * 7 + [2.5] * 7
    series = {START + timedelta(days=i): v for i, v in enumerate(values)}
    result = trend(series, PERIOD)
    assert result.direction is TrendDirection.DECREASING
    assert result.slope_per_week == pytest.approx(-0.5, abs=0.05)
    assert result.n == 28


def test_trend_slope_ignores_missing_days_rather_than_imputing() -> None:
    # Perfect line of +0.1/day with gaps: slope must still be exactly 0.7/week.
    series = {START + timedelta(days=i): 1 + 0.1 * i for i in range(28) if i % 3 != 0}
    result = trend(series, PERIOD)
    assert result.slope_per_week == pytest.approx(0.7)
    assert result.direction is TrendDirection.INCREASING


def test_trend_flat_below_threshold() -> None:
    series = {START + timedelta(days=i): 3.0 + (0.1 if i % 2 else -0.1) for i in range(28)}
    assert trend(series, PERIOD).direction is TrendDirection.FLAT


def test_trend_insufficient_data() -> None:
    series = {START + timedelta(days=i): 3.0 for i in range(6)}
    result = trend(series, PERIOD, min_points=7)
    assert result.direction is TrendDirection.INSUFFICIENT_DATA
    assert result.slope_per_week is None
    assert result.n == 6


@pytest.mark.parametrize(
    ("direction", "polarity", "expected"),
    [
        (TrendDirection.INCREASING, Polarity.HIGHER_IS_BETTER, Outlook.IMPROVING),
        (TrendDirection.DECREASING, Polarity.HIGHER_IS_BETTER, Outlook.WORSENING),
        (TrendDirection.INCREASING, Polarity.HIGHER_IS_WORSE, Outlook.WORSENING),
        (TrendDirection.DECREASING, Polarity.HIGHER_IS_WORSE, Outlook.IMPROVING),
        (TrendDirection.FLAT, Polarity.HIGHER_IS_WORSE, Outlook.STABLE),
        (TrendDirection.INSUFFICIENT_DATA, Polarity.HIGHER_IS_BETTER, Outlook.UNKNOWN),
    ],
)
def test_outlook(direction: TrendDirection, polarity: Polarity, expected: Outlook) -> None:
    assert outlook(direction, polarity) is expected
