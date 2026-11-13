"""Persistence for check-ins.

Repository functions take an explicit `user_id` and never return another
user's rows. Row-Level Security enforces the same rule in the database; the
application-level filter stays as defence in depth.
"""

import uuid
from collections.abc import Iterable
from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, selectinload

from lumen.db import models
from lumen.domain.checkin import Checkin
from lumen.domain.observation import Observation


def create_user(session: Session, email: str) -> uuid.UUID:
    user = models.User(email=email)
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
    """Save the check-in for its local day, replacing any the day already has.

    Scores and tags are replaced, not merged. The upsert is race-safe: two
    concurrent saves for the same day serialize on the row instead of one
    failing on the unique constraint.
    """
    stmt = insert(models.Checkin).values(
        id=uuid.uuid4(),
        user_id=user_id,
        recorded_at=checkin.recorded_at,
        local_date=checkin.local_date,
        mode=checkin.mode,
    )
    checkin_id = session.scalars(
        stmt.on_conflict_do_update(
            index_elements=["user_id", "local_date"],
            set_={"recorded_at": stmt.excluded.recorded_at, "mode": stmt.excluded.mode},
        ).returning(models.Checkin.id)
    ).one()
    for child in (models.CheckinScore, models.CheckinTag):
        session.execute(delete(child).where(child.checkin_id == checkin_id))
    session.execute(
        insert(models.CheckinScore).values(
            [
                {
                    "checkin_id": checkin_id,
                    "user_id": user_id,
                    "dimension": d,
                    "value": v,
                    "volunteered": d in checkin.volunteered,
                }
                for d, v in checkin.scores.items()
            ]
        )
    )
    tags = _get_or_create_tags(session, user_id, checkin.tags)
    if tags:
        session.execute(
            insert(models.CheckinTag).values(
                [{"checkin_id": checkin_id, "user_id": user_id, "tag_id": t.id} for t in tags]
            )
        )
    return checkin_id


def get_checkin(session: Session, user_id: uuid.UUID, local_date: date) -> Checkin | None:
    row = session.scalars(
        select(models.Checkin)
        .where(models.Checkin.user_id == user_id, models.Checkin.local_date == local_date)
        .options(
            selectinload(models.Checkin.scores),
            selectinload(models.Checkin.tags).selectinload(models.CheckinTag.tag),
        )
    ).one_or_none()
    if row is None:
        return None
    return Checkin(
        recorded_at=row.recorded_at,
        local_date=row.local_date,
        scores={s.dimension: s.value for s in row.scores},
        tags=frozenset(t.tag.name for t in row.tags),
        mode=row.mode,
        volunteered=frozenset(s.dimension for s in row.scores if s.volunteered),
    )


def tag_usage(session: Session, user_id: uuid.UUID) -> list[tuple[str, int]]:
    """The user's tags with the number of check-ins using each, most used first.

    Tags no check-in uses any more (after edits) are left out.
    """
    uses = func.count(models.CheckinTag.checkin_id)
    rows = session.execute(
        select(models.Tag.name, uses)
        .join(models.CheckinTag, models.CheckinTag.tag_id == models.Tag.id)
        .where(models.Tag.user_id == user_id)
        .group_by(models.Tag.name)
        .order_by(uses.desc(), models.Tag.name)
    )
    return [(name, count) for name, count in rows]


def list_observations(
    session: Session, user_id: uuid.UUID, start: date, end: date
) -> list[Observation]:
    """The asked scores for a user between `start` and `end` (inclusive), by local date.

    Volunteered scores are left out: they lean towards days that stood out, so statistics on them
    would be biased (spec 008 §2.4). Spec 009 decides how to show them.
    """
    rows = session.execute(
        select(models.Checkin.local_date, models.CheckinScore.dimension, models.CheckinScore.value)
        .join(models.CheckinScore.checkin)
        .where(
            models.Checkin.user_id == user_id,
            models.Checkin.local_date.between(start, end),
            models.CheckinScore.volunteered.is_(False),
        )
        .order_by(models.Checkin.local_date, models.Checkin.recorded_at)
    )
    return [Observation(day=d, dimension=dim, value=v) for d, dim, v in rows]


def get_context(session: Session, user_id: uuid.UUID) -> str:
    """The person's personal context (spec 010), or "" if they have none."""
    found = session.scalar(
        select(models.PersonalContext.text).where(models.PersonalContext.user_id == user_id)
    )
    return found or ""


def save_context(session: Session, user_id: uuid.UUID, value: str, now: datetime) -> None:
    """Replaces the person's personal context. Empty text deletes it."""
    if not value:
        session.execute(
            delete(models.PersonalContext).where(models.PersonalContext.user_id == user_id)
        )
        return
    stmt = insert(models.PersonalContext).values(user_id=user_id, text=value, updated_at=now)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["user_id"],
            set_={"text": stmt.excluded.text, "updated_at": stmt.excluded.updated_at},
        )
    )
