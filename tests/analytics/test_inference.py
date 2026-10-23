import numpy as np
import pytest

from lumen.analytics.inference import (
    bias_corrected_lag1,
    effective_sample_size,
    lag1_autocorrelation,
)


def test_effective_sample_size_shrinks_with_positive_autocorrelation_but_never_grows() -> None:
    assert effective_sample_size(30, 0.5) == pytest.approx(10)
    # Negative autocorrelation is clamped to 0, staying conservative.
    assert effective_sample_size(30, -0.5) == pytest.approx(30)


def test_bias_correction_recovers_autocorrelation_of_short_series() -> None:
    # On short series the raw lag-1 estimate is biased towards zero, which
    # would overstate n_eff and make every interval too narrow.
    rng = np.random.default_rng(7)
    phi, n = 0.5, 20
    raw, corrected = [], []
    for _ in range(1000):
        x = np.zeros(n)
        x[0] = rng.normal()
        for i in range(1, n):
            x[i] = phi * x[i - 1] + rng.normal(0, np.sqrt(1 - phi**2))
        raw.append(lag1_autocorrelation(list(x)))
        corrected.append(bias_corrected_lag1(list(x)))
    assert np.mean(raw) < phi - 0.1
    assert np.mean(corrected) == pytest.approx(phi, abs=0.05)
