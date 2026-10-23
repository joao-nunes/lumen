from datetime import date, timedelta

import numpy as np
import pytest

from lumen.analytics.direction import Direction
from lumen.analytics.series import DailySeries, DateRange
from lumen.analytics.trends import ols_slope, trend

START = date(2026, 1, 1)


def period(days: int) -> DateRange:
    return DateRange(START, START + timedelta(days=days - 1))


def series_from(values: list[float] | np.ndarray) -> DailySeries:
    return {START + timedelta(days=i): float(v) for i, v in enumerate(values)}


def ar1_noise(days: int, sd: float, phi: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = np.zeros(days)
    for i in range(1, days):
        noise[i] = phi * noise[i - 1] + rng.normal(0, sd * np.sqrt(1 - phi**2))
    return noise


def test_ols_slope_exact_line() -> None:
    assert ols_slope([0, 1, 2, 3], [1, 3, 5, 7]) == pytest.approx(2.0)


@pytest.mark.parametrize(
    ("xs", "ys"), [([1.0], [1.0]), ([1.0, 1.0], [1.0, 2.0]), ([1.0, 2.0], [1.0])]
)
def test_ols_slope_rejects_degenerate_input(xs: list[float], ys: list[float]) -> None:
    with pytest.raises(ValueError):
        ols_slope(xs, ys)


def test_perfect_line_has_zero_width_interval() -> None:
    result = trend(series_from([1 + 0.1 * i for i in range(28)]), period(28))
    assert result.direction is Direction.INCREASING
    assert result.slope_per_week == pytest.approx(0.7)
    assert result.ci_low_per_week == pytest.approx(0.7)
    assert result.ci_high_per_week == pytest.approx(0.7)


def test_slope_ignores_missing_days_rather_than_imputing() -> None:
    series = {START + timedelta(days=i): 1 + 0.1 * i for i in range(28) if i % 3 != 0}
    result = trend(series, period(28))
    assert result.slope_per_week == pytest.approx(0.7)
    assert result.n == 18


def test_noisy_decline_is_detected_and_interval_contains_true_slope() -> None:
    days = 28
    true_slope_per_week = -1.5 / (days - 1) * 7
    values = np.linspace(4.0, 2.5, days) + ar1_noise(days, sd=0.3, phi=0.3, seed=1)
    result = trend(series_from(values), period(days))
    assert result.direction is Direction.DECREASING
    assert result.ci_low_per_week is not None and result.ci_high_per_week is not None
    assert result.ci_low_per_week < true_slope_per_week < result.ci_high_per_week


def test_few_noisy_points_are_unclear_not_a_trend() -> None:
    # Like a rotating dimension asked 9 times in 4 weeks: noise must not read as a trend.
    rng = np.random.default_rng(4)
    series = {START + timedelta(days=3 * i): float(3 + rng.normal(0, 0.7)) for i in range(9)}
    result = trend(series, period(28))
    assert result.direction is Direction.UNCLEAR


def test_long_stable_series_is_confidently_flat() -> None:
    values = 3.5 + ar1_noise(90, sd=0.5, phi=0.3, seed=2)
    result = trend(series_from(values), period(90))
    assert result.direction is Direction.FLAT
    assert result.ci_low_per_week is not None and result.ci_high_per_week is not None
    assert -0.1 < result.ci_low_per_week < result.ci_high_per_week < 0.1


def test_real_but_negligible_change_is_flat() -> None:
    # Exact line of 0.05/week: statistically certain, practically irrelevant.
    result = trend(series_from([3 + 0.05 / 7 * i for i in range(28)]), period(28))
    assert result.direction is Direction.FLAT


def test_autocorrelation_widens_the_interval() -> None:
    days = 60
    sticky = 3 + ar1_noise(days, sd=0.5, phi=0.8, seed=3)
    result = trend(series_from(sticky), period(days))
    assert result.n_effective is not None
    assert result.n_effective < 0.5 * result.n


def test_insufficient_points() -> None:
    result = trend(series_from([3.0] * 6), period(28), min_points=7)
    assert result.direction is Direction.INSUFFICIENT_DATA
    assert result.slope_per_week is None
    assert result.n == 6


def test_insufficient_effective_points_reports_slope_without_interval() -> None:
    # A U-shape leaves residuals that are extremely autocorrelated, so n_eff collapses.
    result = trend(series_from([(i - 7) ** 2 / 10 + 0.1 * i for i in range(15)]), period(15))
    assert result.direction is Direction.INSUFFICIENT_DATA
    assert result.slope_per_week is not None
    assert result.ci_low_per_week is None
    assert result.n_effective is not None and result.n_effective < 4


def test_rejects_invalid_confidence() -> None:
    with pytest.raises(ValueError):
        trend(series_from([3.0] * 10), period(10), confidence=1.0)
