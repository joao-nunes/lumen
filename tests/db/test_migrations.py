"""Spec 008 AC-4: the migration labels existing scores with the schedule they were asked under."""

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text

from lumen.domain.dimensions import Dimension, dimensions_for

BEFORE_VOLUNTEERED = "7c41e9a2d6b3"
FIRST, DAYS = date(2026, 1, 1), 730  # all of 2026 and 2027


@pytest.fixture
def alembic_cfg(engine: Engine) -> Iterator[Config]:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    yield cfg
    command.upgrade(cfg, "head")  # whatever happened, leave the database as other tests expect


def test_existing_scores_are_labelled_by_their_day_s_schedule(
    engine: Engine, alembic_cfg: Config
) -> None:
    command.downgrade(alembic_cfg, BEFORE_VOLUNTEERED)
    user = uuid.uuid4()
    days = [FIRST + timedelta(days=i) for i in range(DAYS)]
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO users (id, email, created_at) VALUES (:id, :email, :now)"),
            {"id": user, "email": f"{user}@example.invalid", "now": datetime.now(UTC)},
        )
        checkins = [{"id": uuid.uuid4(), "day": day} for day in days]
        conn.execute(
            text(
                "INSERT INTO checkins (id, user_id, recorded_at, local_date, mode) "
                "VALUES (:id, :user, :at, :day, 'structured')"
            ),
            [{**c, "user": user, "at": datetime.now(UTC)} for c in checkins],
        )
        conn.execute(
            text(
                "INSERT INTO checkin_scores (checkin_id, user_id, dimension, value) "
                "VALUES (:checkin, :user, :dimension, 3)"
            ),
            [
                {"checkin": c["id"], "user": user, "dimension": d.value}
                for c in checkins
                for d in Dimension
            ],
        )
    try:
        command.upgrade(alembic_cfg, "head")

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT c.local_date, s.dimension::text, s.volunteered FROM checkin_scores s "
                    "JOIN checkins c ON c.id = s.checkin_id WHERE s.user_id = :user"
                ),
                {"user": user},
            ).all()
        expected = {(day, d.value, d not in dimensions_for(day)) for day in days for d in Dimension}
        assert set(rows) == expected
        assert len(rows) == DAYS * len(Dimension)
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user})
