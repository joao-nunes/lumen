import pytest

from lumen.analytics.direction import Direction, Outlook, classify, outlook
from lumen.domain.dimensions import Polarity

THRESHOLD = 0.1


@pytest.mark.parametrize(
    ("estimate", "low", "high", "expected"),
    [
        (0.5, 0.2, 0.8, Direction.INCREASING),
        (-0.5, -0.8, -0.2, Direction.DECREASING),
        (0.0, -0.05, 0.05, Direction.FLAT),
        # Interval excludes zero but the effect is too small to matter, and
        # not confidently negligible either.
        (0.08, 0.02, 0.14, Direction.UNCLEAR),
        # Exact but negligible.
        (0.05, 0.05, 0.05, Direction.FLAT),
        # Wide interval spanning zero.
        (0.3, -0.2, 0.8, Direction.UNCLEAR),
    ],
)
def test_classify(estimate: float, low: float, high: float, expected: Direction) -> None:
    assert classify(estimate, low, high, THRESHOLD) is expected


def test_classify_rejects_inverted_interval() -> None:
    with pytest.raises(ValueError):
        classify(0.0, 0.1, -0.1, THRESHOLD)


@pytest.mark.parametrize(
    ("direction", "polarity", "expected"),
    [
        (Direction.INCREASING, Polarity.HIGHER_IS_BETTER, Outlook.IMPROVING),
        (Direction.DECREASING, Polarity.HIGHER_IS_BETTER, Outlook.WORSENING),
        (Direction.INCREASING, Polarity.HIGHER_IS_WORSE, Outlook.WORSENING),
        (Direction.DECREASING, Polarity.HIGHER_IS_WORSE, Outlook.IMPROVING),
        (Direction.FLAT, Polarity.HIGHER_IS_WORSE, Outlook.STABLE),
        (Direction.UNCLEAR, Polarity.HIGHER_IS_BETTER, Outlook.UNKNOWN),
        (Direction.INSUFFICIENT_DATA, Polarity.HIGHER_IS_BETTER, Outlook.UNKNOWN),
    ],
)
def test_outlook(direction: Direction, polarity: Polarity, expected: Outlook) -> None:
    assert outlook(direction, polarity) is expected
