from datetime import date, timedelta

import numpy as np
import pytest

from lumen.analytics.direction import Direction
from lumen.analytics.series import DailySeries, DateRange
from lumen.analytics.trends import trend

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


def test_perfect_line_has_exact_slope_and_zero_width_interval() -> None:
    result = trend(series_from([1 + 0.1 * i for i in range(28)]), period(28))
    assert result.direction is Direction.INCREASING
    assert result.slope_per_week == result.ci_low_per_week == pytest.approx(0.7)


def test_missing_days_are_skipped_not_imputed() -> None:
    series = {START + timedelta(days=i): 1 + 0.1 * i for i in range(28) if i % 3 != 0}
    result = trend(series, period(28))
    assert result.slope_per_week == pytest.approx(0.7)
    assert result.n == 18


def test_noisy_decline_is_detected_and_interval_contains_true_slope() -> None:
    days = 28
    true_slope = -1.5 / (days - 1) * 7
    result = trend(
        series_from(np.linspace(4.0, 2.5, days) + ar1_noise(days, 0.3, 0.3, seed=1)), period(days)
    )
    assert result.direction is Direction.DECREASING
    assert result.ci_low_per_week is not None and result.ci_high_per_week is not None
    assert result.ci_low_per_week < true_slope < result.ci_high_per_week


def test_few_noisy_points_are_unclear_rather_than_a_trend() -> None:
    rng = np.random.default_rng(4)
    series = {START + timedelta(days=3 * i): float(3 + rng.normal(0, 0.7)) for i in range(9)}
    assert trend(series, period(28)).direction is Direction.UNCLEAR


def test_long_stable_series_is_confidently_flat() -> None:
    result = trend(series_from(3.5 + ar1_noise(90, 0.5, 0.3, seed=2)), period(90))
    assert result.direction is Direction.FLAT


def test_autocorrelation_reduces_the_effective_sample_size() -> None:
    result = trend(series_from(3 + ar1_noise(60, 0.5, 0.8, seed=3)), period(60))
    assert result.n_effective is not None
    assert result.n_effective < 0.5 * result.n


def test_too_few_points_is_insufficient_data() -> None:
    result = trend(series_from([3.0] * 6), period(28))
    assert result.direction is Direction.INSUFFICIENT_DATA
    assert result.slope_per_week is None
