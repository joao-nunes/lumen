import pytest

from lumen.analytics.inference import (
    bias_corrected_lag1,
    effective_sample_size,
    lag1_autocorrelation,
    t_critical,
)


def test_lag1_autocorrelation() -> None:
    assert lag1_autocorrelation([1, -1, 1, -1, 1, -1]) < -0.8
    assert lag1_autocorrelation([1, 2, 3, 4, 5, 6]) > 0.4
    assert lag1_autocorrelation([3, 3, 3]) == 0.0
    assert lag1_autocorrelation([3]) == 0.0


def test_effective_sample_size_shrinks_with_positive_autocorrelation_only() -> None:
    assert effective_sample_size(30, 0.0) == pytest.approx(30)
    assert effective_sample_size(30, 0.5) == pytest.approx(10)
    # Negative autocorrelation is clamped, never inflating n.
    assert effective_sample_size(30, -0.5) == pytest.approx(30)


def test_t_critical_known_values() -> None:
    assert t_critical(0.95, 10) == pytest.approx(2.228, abs=1e-3)
    assert t_critical(0.95, 1e6) == pytest.approx(1.960, abs=1e-3)


@pytest.mark.parametrize(("confidence", "dof"), [(0.0, 10), (1.0, 10), (0.95, 0)])
def test_t_critical_rejects_invalid_arguments(confidence: float, dof: float) -> None:
    with pytest.raises(ValueError):
        t_critical(confidence, dof)


def test_bias_correction_raises_short_series_autocorrelation() -> None:
    values = [3.0, 3.4, 3.1, 2.6, 2.9, 3.3, 3.6, 3.2, 2.8, 3.0]
    assert bias_corrected_lag1(values) > lag1_autocorrelation(values)
