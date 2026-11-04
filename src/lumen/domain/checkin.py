"""Check-in domain objects, independent of persistence."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum

from lumen.domain.dimensions import CORE_DIMENSIONS, Dimension, validate_score

_TAG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_TAGS = 20
# How many days back a check-in can be entered or edited (spec 002, Q2).
BACKFILL_DAYS = 7


class CheckinMode(StrEnum):
    STRUCTURED = "structured"
    FREE_TEXT = "free_text"


class InvalidTagError(ValueError):
    pass


class TooManyTagsError(ValueError):
    pass


class UnknownDimensionError(ValueError):
    pass


class MissingCoreDimensionError(ValueError):
    pass


class DateOutOfRangeError(ValueError):
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
        if len(self.tags) > MAX_TAGS:
            raise TooManyTagsError(f"A check-in can have at most {MAX_TAGS} tags")


def structured_scores(raw: Mapping[str, int]) -> dict[Dimension, int]:
    """Scores entered on the check-in form: known dimensions only, every core one present."""
    try:
        scores = {Dimension(key): value for key, value in raw.items()}
    except ValueError:
        unknown = sorted(set(raw) - set(Dimension))
        raise UnknownDimensionError(f"Unknown dimension(s): {', '.join(unknown)}") from None
    missing = [d.value for d in CORE_DIMENSIONS if d not in scores]
    if missing:
        raise MissingCoreDimensionError(f"Missing core dimension(s): {', '.join(missing)}")
    return scores


def check_editable(local_date: date, now: datetime) -> None:
    """Allow today and the previous BACKFILL_DAYS days, in any timezone.

    The server can't know the user's timezone, so the window is widened by one
    day either way of the UTC date: timezones run from UTC-12 to UTC+14.
    """
    today_utc = now.astimezone(UTC).date()
    first = today_utc - timedelta(days=BACKFILL_DAYS + 1)
    last = today_utc + timedelta(days=1)
    if not first <= local_date <= last:
        raise DateOutOfRangeError(f"Check-ins can be saved from {first} to {last}")
