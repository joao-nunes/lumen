"""Check-in endpoints (spec 002 §2.3). Orchestration only: rules live in lumen.domain."""

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field, StrictInt

from lumen.api.dependencies import ContainerDep, CurrentUser, UserDb
from lumen.db.repository import get_checkin, save_checkin, tag_usage
from lumen.domain.checkin import Checkin, check_editable, structured_scores
from lumen.domain.dimensions import DIMENSIONS, Cadence, Dimension, Polarity, dimensions_for

router = APIRouter(prefix="/api")

# Bounds on request size only; the domain applies the real limits (e.g. 20 tags).
ShortText = Annotated[str, Field(max_length=100)]


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


class CheckinOut(BaseModel):
    scores: dict[Dimension, int]
    tags: list[str]
    recorded_at: datetime


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
        ),
    )


@router.get("/dimensions")
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


@router.get("/checkins/{local_date}")
def read_checkin(local_date: date, user: CurrentUser, db: UserDb) -> DayOut:
    return _day(local_date, get_checkin(db, user.user_id, local_date))


@router.put("/checkins/{local_date}")
def write_checkin(
    local_date: date, body: CheckinIn, user: CurrentUser, db: UserDb, container: ContainerDep
) -> DayOut:
    now = container.clock()
    check_editable(local_date, now)
    checkin = Checkin(
        recorded_at=now,
        local_date=local_date,
        scores=structured_scores(body.scores),
        tags=frozenset(body.tags),
    )
    save_checkin(db, user.user_id, checkin)
    return _day(local_date, checkin)


@router.get("/tags")
def list_tags(user: CurrentUser, db: UserDb) -> list[TagOut]:
    return [TagOut(name=name, count=count) for name, count in tag_usage(db, user.user_id)]
