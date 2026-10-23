"""Turning an estimate and its confidence interval into a direction, and a
direction into an outlook.

The same rule applies to trend slopes and to period changes:

- INCREASING / DECREASING: the interval excludes zero *and* the estimate is
  at least `threshold` in magnitude (statistically and practically clear).
- FLAT: the whole interval lies within ±`threshold`, i.e. we are confident
  any change is too small to matter.
- UNCLEAR: anything else; the data cannot distinguish a change from noise.
- INSUFFICIENT_DATA: too little data to compute an interval at all.
"""

from enum import StrEnum

from lumen.domain.dimensions import Polarity


class Direction(StrEnum):
    INCREASING = "increasing"
    DECREASING = "decreasing"
    FLAT = "flat"
    UNCLEAR = "unclear"
    INSUFFICIENT_DATA = "insufficient_data"


class Outlook(StrEnum):
    """Direction interpreted through the dimension's polarity."""

    IMPROVING = "improving"
    WORSENING = "worsening"
    STABLE = "stable"
    UNKNOWN = "unknown"


def classify(estimate: float, ci_low: float, ci_high: float, threshold: float) -> Direction:
    if ci_low > ci_high:
        raise ValueError("ci_low must not exceed ci_high")
    if threshold < 0:
        raise ValueError("threshold must be non-negative")
    if (ci_low > 0 or ci_high < 0) and abs(estimate) >= threshold:
        return Direction.INCREASING if estimate > 0 else Direction.DECREASING
    if -threshold < ci_low and ci_high < threshold:
        return Direction.FLAT
    return Direction.UNCLEAR


def outlook(direction: Direction, polarity: Polarity) -> Outlook:
    if direction in (Direction.INSUFFICIENT_DATA, Direction.UNCLEAR):
        return Outlook.UNKNOWN
    if direction is Direction.FLAT:
        return Outlook.STABLE
    rising = direction is Direction.INCREASING
    if rising == (polarity is Polarity.HIGHER_IS_BETTER):
        return Outlook.IMPROVING
    return Outlook.WORSENING
