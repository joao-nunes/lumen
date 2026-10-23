from datetime import date, timedelta

import pytest

from lumen.analytics.direction import Direction
from lumen.analytics.series import DateRange
from lumen.analytics.trends import trend

START = date(2026, 1, 1)


def test_exact_line_with_gaps_gives_exact_weekly_slope_from_observed_days_only() -> None:
    # Missing days must be skipped, not imputed; zero residuals give a zero-width interval.
    series = {START + timedelta(days=i): 1 + 0.1 * i for i in range(28) if i % 3 != 0}
    result = trend(series, DateRange(START, START + timedelta(days=27)))
    assert (
        result.slope_per_week,
        result.ci_low_per_week,
        result.ci_high_per_week,
        result.direction,
        result.n,
    ) == (pytest.approx(0.7), pytest.approx(0.7), pytest.approx(0.7), Direction.INCREASING, 18)


def test_strongly_autocorrelated_data_reports_slope_but_no_interval() -> None:
    # A U-shape leaves extremely autocorrelated residuals (n_eff < 4). Computing
    # an interval there would need <= 0 degrees of freedom and crash.
    series = {START + timedelta(days=i): (i - 7) ** 2 / 10 + 0.1 * i for i in range(15)}
    result = trend(series, DateRange(START, START + timedelta(days=14)))
    assert result.direction is Direction.INSUFFICIENT_DATA
    assert result.slope_per_week is not None
    assert (result.ci_low_per_week, result.ci_high_per_week) == (None, None)
