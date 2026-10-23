"""Do the 95% intervals actually contain the truth ~95% of the time?

Simulates realistic check-in data (autocorrelated, rounded to the 1-5 scale,
with skipped days) where the true change or slope is known, and measures
how often the intervals cover it. Seeds are fixed, so results are
deterministic.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from lumen.analytics.metrics import period_change
from lumen.analytics.series import DailySeries, DateRange
from lumen.analytics.trends import trend

START = date(2026, 1, 1)
SIMULATIONS = 400
# Nominal 95%; allow for Monte Carlo error (±~2.2% at 400 runs) and the
# approximations documented in lumen.analytics.inference.
MIN_COVERAGE = 0.91


def simulate(
    rng: np.random.Generator, level: np.ndarray, phi: float, skip: float, sd: float = 0.6
) -> DailySeries:
    days = len(level)
    noise = np.empty(days)
    noise[0] = rng.normal(0, sd)
    for i in range(1, days):
        noise[i] = phi * noise[i - 1] + rng.normal(0, sd * np.sqrt(1 - phi**2))
    values = np.clip(np.round(level + noise), 1, 5)
    return {
        START + timedelta(days=i): float(v) for i, v in enumerate(values) if rng.random() >= skip
    }


@pytest.mark.parametrize("phi", [0.0, 0.3, 0.5])
@pytest.mark.parametrize("skip", [0.2, 0.5])
def test_period_change_interval_coverage(phi: float, skip: float) -> None:
    rng = np.random.default_rng(1000)
    current = DateRange(START + timedelta(days=28), START + timedelta(days=55))
    covered = total = 0
    for _ in range(SIMULATIONS):
        change = period_change(simulate(rng, np.full(56, 3.0), phi, skip), current)
        if change.ci_low is not None and change.ci_high is not None:
            total += 1
            covered += change.ci_low <= 0 <= change.ci_high
    assert total >= SIMULATIONS / 2
    assert covered / total >= MIN_COVERAGE


@pytest.mark.parametrize("phi", [0.0, 0.3, 0.5])
@pytest.mark.parametrize("skip", [0.2, 0.5])
def test_trend_interval_coverage(phi: float, skip: float) -> None:
    rng = np.random.default_rng(2000)
    true_slope_per_day = 0.01
    level = 2.6 + true_slope_per_day * np.arange(84)
    period = DateRange(START, START + timedelta(days=83))
    covered = total = 0
    for _ in range(SIMULATIONS):
        result = trend(simulate(rng, level, phi, skip), period)
        if result.ci_low_per_week is not None and result.ci_high_per_week is not None:
            total += 1
            covered += result.ci_low_per_week <= true_slope_per_day * 7 <= result.ci_high_per_week
    assert total >= SIMULATIONS / 2
    assert covered / total >= MIN_COVERAGE
