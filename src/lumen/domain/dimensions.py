"""Wellbeing dimensions, their scale, cadence, polarity, and anchor labels.

Dimensions are defined in code (not the database) so that their meaning is
versioned alongside the analytics that depend on it. See PROJECT.MD §6.1.
"""

from dataclasses import dataclass
from datetime import date
from enum import StrEnum

SCALE_MIN = 1
SCALE_MAX = 5


class Dimension(StrEnum):
    MOOD = "mood"
    ENERGY = "energy"
    STRESS = "stress"
    SLEEP_QUALITY = "sleep_quality"
    MOTIVATION = "motivation"
    CONCENTRATION = "concentration"
    SOCIAL_CONNECTION = "social_connection"


class Cadence(StrEnum):
    CORE = "core"
    ROTATING = "rotating"


class Polarity(StrEnum):
    """Whether a higher score means the user is doing better or worse."""

    HIGHER_IS_BETTER = "higher_is_better"
    HIGHER_IS_WORSE = "higher_is_worse"


@dataclass(frozen=True, slots=True)
class Anchor:
    label: str
    description: str


@dataclass(frozen=True, slots=True)
class DimensionSpec:
    dimension: Dimension
    display_name: str
    cadence: Cadence
    polarity: Polarity
    # anchors[i] describes score i + SCALE_MIN.
    anchors: tuple[Anchor, Anchor, Anchor, Anchor, Anchor]

    def anchor_for(self, value: int) -> Anchor:
        validate_score(value)
        return self.anchors[value - SCALE_MIN]


# Anchor wording is a first draft (open question in PROJECT.MD §18).
DIMENSIONS: dict[Dimension, DimensionSpec] = {
    spec.dimension: spec
    for spec in (
        DimensionSpec(
            Dimension.MOOD,
            "Mood",
            Cadence.CORE,
            Polarity.HIGHER_IS_BETTER,
            (
                Anchor("Very low", "Struggling to feel anything positive"),
                Anchor("Low", "Mostly down, with brief better moments"),
                Anchor("Neutral", "Neither good nor bad"),
                Anchor("Good", "Generally positive"),
                Anchor("Very good", "Clearly positive, light, engaged"),
            ),
        ),
        DimensionSpec(
            Dimension.ENERGY,
            "Energy",
            Cadence.CORE,
            Polarity.HIGHER_IS_BETTER,
            (
                Anchor("Depleted", "Hard to get through basic tasks"),
                Anchor("Low", "Running on reserves"),
                Anchor("Moderate", "Enough for what the day needs"),
                Anchor("Good", "Energy to spare for extra things"),
                Anchor("High", "Energised and ready for anything"),
            ),
        ),
        DimensionSpec(
            Dimension.STRESS,
            "Stress",
            Cadence.CORE,
            Polarity.HIGHER_IS_WORSE,
            (
                Anchor("Calm", "Relaxed, nothing pressing"),
                Anchor("Mild", "Some pressure, easily manageable"),
                Anchor("Moderate", "Noticeable pressure, still in control"),
                Anchor("High", "Struggling to keep up, tense"),
                Anchor("Overwhelmed", "Feels like too much to cope with"),
            ),
        ),
        DimensionSpec(
            Dimension.SLEEP_QUALITY,
            "Sleep quality",
            Cadence.ROTATING,
            Polarity.HIGHER_IS_BETTER,
            (
                Anchor("Very poor", "Barely slept or woke up exhausted"),
                Anchor("Poor", "Restless or too short"),
                Anchor("Okay", "Adequate but not refreshing"),
                Anchor("Good", "Woke up mostly rested"),
                Anchor("Very good", "Deep, refreshing sleep"),
            ),
        ),
        DimensionSpec(
            Dimension.MOTIVATION,
            "Motivation",
            Cadence.ROTATING,
            Polarity.HIGHER_IS_BETTER,
            (
                Anchor("None", "Could not get myself to start anything"),
                Anchor("Low", "Only did what was strictly necessary"),
                Anchor("Moderate", "Got things done with some effort"),
                Anchor("Good", "Wanted to make progress"),
                Anchor("High", "Driven and eager"),
            ),
        ),
        DimensionSpec(
            Dimension.CONCENTRATION,
            "Concentration",
            Cadence.ROTATING,
            Polarity.HIGHER_IS_BETTER,
            (
                Anchor("Scattered", "Could not hold focus at all"),
                Anchor("Poor", "Frequently distracted"),
                Anchor("Okay", "Focused in short stretches"),
                Anchor("Good", "Focused most of the time"),
                Anchor("Sharp", "Deep, sustained focus"),
            ),
        ),
        DimensionSpec(
            Dimension.SOCIAL_CONNECTION,
            "Social connection",
            Cadence.ROTATING,
            Polarity.HIGHER_IS_BETTER,
            (
                Anchor("Isolated", "Felt alone or cut off"),
                Anchor("Distant", "Little meaningful contact"),
                Anchor("Some", "Some contact, neutral"),
                Anchor("Connected", "Meaningful contact with others"),
                Anchor("Very connected", "Felt close and supported"),
            ),
        ),
    )
}

CORE_DIMENSIONS: tuple[Dimension, ...] = tuple(
    d for d, spec in DIMENSIONS.items() if spec.cadence is Cadence.CORE
)
ROTATING_DIMENSIONS: tuple[Dimension, ...] = tuple(
    d for d, spec in DIMENSIONS.items() if spec.cadence is Cadence.ROTATING
)


class InvalidScoreError(ValueError):
    pass


def validate_score(value: int) -> int:
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidScoreError(f"Score must be an int, got {type(value).__name__}")
    if not SCALE_MIN <= value <= SCALE_MAX:
        raise InvalidScoreError(f"Score must be between {SCALE_MIN} and {SCALE_MAX}, got {value}")
    return value


def rotating_dimensions_for(day: date, per_day: int = 2) -> tuple[Dimension, ...]:
    """Rotating dimensions to ask on a given day.

    Provisional schedule (PROJECT.MD §18): cycle through the rotating
    dimensions in order, `per_day` at a time, keyed on the ordinal date so the
    result is deterministic and every dimension is asked regularly.
    """
    if not 0 <= per_day <= len(ROTATING_DIMENSIONS):
        raise ValueError(f"per_day must be between 0 and {len(ROTATING_DIMENSIONS)}")
    n = len(ROTATING_DIMENSIONS)
    start = (day.toordinal() * per_day) % n
    return tuple(ROTATING_DIMENSIONS[(start + i) % n] for i in range(per_day))


def dimensions_for(day: date, rotating_per_day: int = 2) -> tuple[Dimension, ...]:
    return CORE_DIMENSIONS + rotating_dimensions_for(day, rotating_per_day)
