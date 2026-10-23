"""Persistence for check-ins.

Repository functions take an explicit `user_id` and never return another
user's rows. Row-Level Security will enforce the same rule in the database;
the application-level filter stays as defence in depth.
"""

import uuid
from collections.abc import Iterable
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from lumen.db import models
from lumen.domain.checkin import Checkin
from lumen.domain.observation import Observation


def create_user(session: Session) -> uuid.UUID:
    user = models.User()
    session.add(user)
    session.flush()
    return user.id


def _get_or_create_tags(
    session: Session, user_id: uuid.UUID, names: Iterable[str]
) -> list[models.Tag]:
    names = sorted(set(names))
    if not names:
        return []
    # ON CONFLICT DO NOTHING makes concurrent creation of the same tag safe.
    session.execute(
        insert(models.Tag)
        .values([{"id": uuid.uuid4(), "user_id": user_id, "name": n} for n in names])
        .on_conflict_do_nothing(index_elements=["user_id", "name"])
    )
    return list(
        session.scalars(
            select(models.Tag).where(models.Tag.user_id == user_id, models.Tag.name.in_(names))
        )
    )


def save_checkin(session: Session, user_id: uuid.UUID, checkin: Checkin) -> uuid.UUID:
    row = models.Checkin(
        user_id=user_id,
        recorded_at=checkin.recorded_at,
        local_date=checkin.local_date,
        mode=checkin.mode,
        scores=[
            models.CheckinScore(dimension=dimension, value=value, user_id=user_id)
            for dimension, value in checkin.scores.items()
        ],
        tags=[
            models.CheckinTag(tag=tag, user_id=user_id)
            for tag in _get_or_create_tags(session, user_id, checkin.tags)
        ],
    )
    session.add(row)
    session.flush()
    return row.id


def list_observations(
    session: Session, user_id: uuid.UUID, start: date, end: date
) -> list[Observation]:
    """All scores for a user between `start` and `end` (inclusive), by local date."""
    rows = session.execute(
        select(models.Checkin.local_date, models.CheckinScore.dimension, models.CheckinScore.value)
        .join(models.CheckinScore.checkin)
        .where(
            models.Checkin.user_id == user_id,
            models.Checkin.local_date.between(start, end),
        )
        .order_by(models.Checkin.local_date, models.Checkin.recorded_at)
    )
    return [Observation(day=d, dimension=dim, value=v) for d, dim, v in rows]
