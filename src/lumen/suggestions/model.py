"""What a suggestion is, and the seam any model sits behind (spec 006 §2.5)."""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

from lumen.domain.dimensions import SCALE_MAX, SCALE_MIN, Dimension

# PROJECT.MD §4.2. Offered to the model alongside a person's own tags.
STARTER_TAGS = (
    "exercise",
    "alcohol",
    "caffeine_late",
    "social_time",
    "workday",
    "therapy_day",
    "poor_sleep",
    "conflict",
    "time_outdoors",
)


def offered_tags(used: Iterable[str]) -> tuple[str, ...]:
    """What the model may choose: a person's own tags first, then the starter tags, once each."""
    return tuple(dict.fromkeys([*used, *STARTER_TAGS]))


class SuggestionsUnavailableError(Exception):
    """The model couldn't give a usable answer. The message never repeats the text."""

    def __init__(self) -> None:
        super().__init__("The local model is unavailable")


@dataclass(frozen=True, slots=True)
class Suggestion:
    scores: Mapping[Dimension, int] = field(default_factory=dict)
    tags: frozenset[str] = frozenset()


class SuggestionModel(Protocol):
    def suggest(
        self, text: str, dimensions: Collection[Dimension], tags: Collection[str]
    ) -> Suggestion: ...


def keep_valid(
    scores: Mapping[str, object],
    tags: Collection[object],
    asked: Collection[Dimension],
    offered: Collection[str],
) -> Suggestion:
    """Only what was asked for: a schema enforces a reply's shape, not that its values are right."""
    return Suggestion(
        scores={
            dimension: value
            for dimension in asked
            if type(value := scores.get(dimension.value)) is int and SCALE_MIN <= value <= SCALE_MAX
        },
        tags=frozenset(tag for tag in tags if isinstance(tag, str) and tag in offered),
    )
