import pytest

from lumen.analytics.direction import Direction, Outlook, classify, outlook
from lumen.domain.dimensions import Polarity

THRESHOLD = 0.1


@pytest.mark.parametrize(
    ("estimate", "low", "high", "expected"),
    [
        (0.5, 0.2, 0.8, Direction.INCREASING),  # clear and large enough
        (0.0, -0.05, 0.05, Direction.FLAT),  # confidently negligible
        (0.05, 0.05, 0.05, Direction.FLAT),  # certain but too small to matter
        (0.08, 0.02, 0.14, Direction.UNCLEAR),  # excludes zero, but may or may not matter
        (0.3, -0.2, 0.8, Direction.UNCLEAR),  # interval spans zero
    ],
)
def test_classify(estimate: float, low: float, high: float, expected: Direction) -> None:
    assert classify(estimate, low, high, THRESHOLD) is expected


@pytest.mark.parametrize(
    ("direction", "polarity", "expected"),
    [
        (Direction.INCREASING, Polarity.HIGHER_IS_BETTER, Outlook.IMPROVING),
        (Direction.INCREASING, Polarity.HIGHER_IS_WORSE, Outlook.WORSENING),
        (Direction.FLAT, Polarity.HIGHER_IS_WORSE, Outlook.STABLE),
        (Direction.UNCLEAR, Polarity.HIGHER_IS_BETTER, Outlook.UNKNOWN),
    ],
)
def test_outlook_applies_polarity(
    direction: Direction, polarity: Polarity, expected: Outlook
) -> None:
    assert outlook(direction, polarity) is expected
