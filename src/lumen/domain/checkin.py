"""Check-in domain objects, independent of persistence."""

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from lumen.domain.dimensions import Dimension, validate_score

_TAG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class CheckinMode(StrEnum):
    STRUCTURED = "structured"
    FREE_TEXT = "free_text"


class InvalidTagError(ValueError):
    pass


def normalize_tag(name: str) -> str:
    """Normalize a tag to snake_case, e.g. "Time outdoors" -> "time_outdoors"."""
    normalized = re.sub(r"[\s\-]+", "_", name.strip().lower())
    if not _TAG_PATTERN.fullmatch(normalized):
        raise InvalidTagError(
            f"Invalid tag {name!r}: use letters, digits and underscores, "
            "starting with a letter, max 40 characters"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class Checkin:
    recorded_at: datetime
    # The user's calendar day for this check-in. Stored explicitly rather than
    # derived from recorded_at, because "which day" depends on the user's
    # timezone at the time of recording.
    local_date: date
    scores: dict[Dimension, int]
    tags: frozenset[str] = field(default_factory=frozenset)
    mode: CheckinMode = CheckinMode.STRUCTURED

    def __post_init__(self) -> None:
        if self.recorded_at.tzinfo is None:
            raise ValueError("recorded_at must be timezone-aware")
        if not self.scores:
            raise ValueError("A check-in needs at least one score")
        for value in self.scores.values():
            validate_score(value)
        object.__setattr__(self, "tags", frozenset(normalize_tag(t) for t in self.tags))
