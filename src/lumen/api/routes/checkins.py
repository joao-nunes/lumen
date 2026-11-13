"""Check-in endpoints (spec 002 §2.3). Orchestration only: rules live in lumen.domain."""

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictInt, StringConstraints

from lumen.api.dependencies import ContainerDep, CurrentUser, UserDb
from lumen.api.errors import error_responses
from lumen.db.repository import get_checkin, save_checkin, tag_usage
from lumen.db.scope import user_transaction
from lumen.domain.checkin import (
    Checkin,
    CheckinMode,
    check_editable,
    structured_scores,
    volunteered_for,
)
from lumen.domain.dimensions import DIMENSIONS, Cadence, Dimension, Polarity, dimensions_for
from lumen.suggestions.model import SuggestionsUnavailableError, keep_valid, offered_tags

router = APIRouter(prefix="/api")

# Bounds on request size only; the domain applies the real limits (e.g. 20 tags).
ShortText = Annotated[str, Field(max_length=100)]
# Tier 0: never stored or logged, and never repeated in an error (spec 006 §2.4).
NoteText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class AnchorOut(BaseModel):
    label: str
    description: str


class DimensionOut(BaseModel):
    key: Dimension
    display_name: str
    cadence: Cadence
    polarity: Polarity
    anchors: list[AnchorOut]


class CheckinIn(BaseModel):
    scores: dict[ShortText, StrictInt] = Field(max_length=len(Dimension) * 2)
    tags: list[ShortText] = Field(default_factory=list, max_length=100)
    mode: CheckinMode = CheckinMode.STRUCTURED


class SuggestionIn(BaseModel):
    text: NoteText


class SuggestionOut(BaseModel):
    scores: dict[Dimension, int]
    tags: list[str]


class CheckinOut(BaseModel):
    scores: dict[Dimension, int]
    tags: list[str]
    recorded_at: datetime
    # Scored dimensions the day didn't ask about (spec 008). Set by the server, never the client.
    volunteered: list[Dimension]


class DayOut(BaseModel):
    local_date: date
    # Which dimensions the form asks that day: the core ones plus that day's rotating ones.
    prompted: list[Dimension]
    checkin: CheckinOut | None


class TagOut(BaseModel):
    name: str
    count: int


def _day(local_date: date, checkin: Checkin | None) -> DayOut:
    return DayOut(
        local_date=local_date,
        prompted=list(dimensions_for(local_date)),
        checkin=None
        if checkin is None
        else CheckinOut(
            scores=checkin.scores,
            tags=sorted(checkin.tags),
            recorded_at=checkin.recorded_at.astimezone(UTC),
            volunteered=sorted(checkin.volunteered),
        ),
    )


@router.get("/dimensions", responses=error_responses(401))
def list_dimensions(_user: CurrentUser) -> list[DimensionOut]:
    return [
        DimensionOut(
            key=spec.dimension,
            display_name=spec.display_name,
            cadence=spec.cadence,
            polarity=spec.polarity,
            anchors=[AnchorOut(label=a.label, description=a.description) for a in spec.anchors],
        )
        for spec in DIMENSIONS.values()
    ]


@router.get("/checkins/{local_date}", responses=error_responses(401, 422))
def read_checkin(local_date: date, user: CurrentUser, db: UserDb) -> DayOut:
    return _day(local_date, get_checkin(db, user.user_id, local_date))


@router.put("/checkins/{local_date}", responses=error_responses(401, 403, 415, 422))
def write_checkin(
    local_date: date, body: CheckinIn, user: CurrentUser, db: UserDb, container: ContainerDep
) -> DayOut:
    now = container.clock()
    check_editable(local_date, now)
    scores = structured_scores(body.scores)
    checkin = Checkin(
        recorded_at=now,
        local_date=local_date,
        scores=scores,
        tags=frozenset(body.tags),
        mode=body.mode,
        volunteered=volunteered_for(local_date, scores),
    )
    save_checkin(db, user.user_id, checkin)
    return _day(local_date, checkin)


@router.post(
    "/checkins/{local_date}/suggestion", responses=error_responses(401, 403, 415, 422, 503)
)
def suggest_checkin(
    local_date: date, body: SuggestionIn, user: CurrentUser, container: ContainerDep
) -> SuggestionOut:
    """Suggested scores and tags from the local model. Saves nothing, and keeps nothing."""
    check_editable(local_date, container.clock())
    if container.suggestions is None:
        raise SuggestionsUnavailableError
    # A short transaction, not UserDb: a model call can take many seconds.
    with user_transaction(container.app_sessions, user.user_id) as db:
        used = [name for name, _ in tag_usage(db, user.user_id)]
    asked = dimensions_for(local_date)
    offered = offered_tags(used)
    reply = container.suggestions.suggest(body.text, asked, offered)
    valid = keep_valid(
        {dimension.value: score for dimension, score in reply.scores.items()},
        reply.tags,
        asked,
        offered,
    )
    return SuggestionOut(scores=dict(valid.scores), tags=sorted(valid.tags))


@router.get("/tags", responses=error_responses(401))
def list_tags(user: CurrentUser, db: UserDb) -> list[TagOut]:
    return [TagOut(name=name, count=count) for name, count in tag_usage(db, user.user_id)]
