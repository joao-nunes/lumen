"""Row-level security: the database itself keeps each user's data private,
even when application queries forget to filter by user."""

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from lumen.db import models
from lumen.db.repository import save_checkin
from lumen.db.scope import USER_SETTING, user_transaction
from lumen.domain.checkin import Checkin
from lumen.domain.dimensions import Dimension
from tests.db.factories import new_user
from tests.db.roles import APP, AUTH, act_as

DAY = date(2026, 10, 23)


def checkin(mood: int) -> Checkin:
    return Checkin(
        datetime(2026, 10, 23, 21, tzinfo=UTC),
        DAY,
        {Dimension.MOOD: mood},
        frozenset({"exercise"}),
    )


def test_every_user_owned_table_is_protected_and_runtime_roles_cannot_bypass_it(
    session: Session,
) -> None:
    # Guards against a future table with user data being added without RLS.
    tables = session.execute(
        text(
            """
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   EXISTS (SELECT FROM pg_policies p
                           WHERE p.schemaname = 'public' AND p.tablename = c.relname
                             AND :app = ANY (p.roles))
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND (c.relname = 'users' OR EXISTS (
                  SELECT FROM pg_attribute a
                  WHERE a.attrelid = c.oid AND a.attname = 'user_id' AND NOT a.attisdropped))
            """
        ),
        {"app": APP},
    ).all()
    assert len(tables) >= 5
    assert [(name, True, True, True) for name, *_ in tables] == [tuple(t) for t in tables]

    roles = session.execute(
        text(
            "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles "
            "WHERE rolname IN (:app, :auth) ORDER BY rolname"
        ),
        {"app": APP, "auth": AUTH},
    ).all()
    assert [tuple(r) for r in roles] == [(APP, False, False), (AUTH, False, False)]


def test_app_sees_only_the_current_users_rows_without_any_filter(session: Session) -> None:
    alice, bob = new_user(session), new_user(session)
    save_checkin(session, alice, checkin(mood=4))
    save_checkin(session, bob, checkin(mood=1))

    act_as(session, APP, alice)
    owners = {
        "users": set(session.scalars(select(models.User.id))),
        **{
            table.__tablename__: set(session.scalars(select(table.user_id)))
            for table in (models.Checkin, models.CheckinScore, models.Tag, models.CheckinTag)
        },
    }
    assert owners == {table: {alice} for table in owners}


def test_app_cannot_write_rows_for_another_user(session: Session) -> None:
    alice, bob = new_user(session), new_user(session)
    act_as(session, APP, alice)
    # A plain INSERT, deliberately without RETURNING: ORM inserts use RETURNING,
    # whose read policy would fail first and hide a missing write check.
    with pytest.raises(ProgrammingError, match="row-level security"):
        session.execute(
            text("INSERT INTO tags (id, user_id, name) VALUES (gen_random_uuid(), :bob, 'x')"),
            {"bob": bob},
        )


def test_without_a_current_user_the_app_sees_nothing_and_does_not_fail(
    session: Session,
) -> None:
    save_checkin(session, new_user(session), checkin(mood=3))
    act_as(session, APP)
    assert session.scalar(select(func.count()).select_from(models.Checkin)) == 0
    # After a transaction-local setting ends, Postgres reports '' rather than
    # NULL; that must also mean "nobody", not an invalid-uuid error.
    session.execute(select(func.set_config(USER_SETTING, "", True)))
    assert session.scalar(select(func.count()).select_from(models.Checkin)) == 0


@pytest.mark.parametrize(
    ("role", "query"),
    [(APP, "SELECT FROM auth.sessions"), (AUTH, "SELECT FROM checkins")],
)
def test_each_role_is_denied_the_other_components_data(
    session: Session, role: str, query: str
) -> None:
    act_as(session, role)
    with pytest.raises(ProgrammingError, match="permission denied"):
        session.execute(text(query))


def test_user_scope_ends_with_its_transaction_and_never_leaks_to_the_next(
    engine: Engine,
) -> None:
    # Pooled connections are reused across requests: if the scope outlived its
    # transaction, the next request on this connection would act as this user.
    user_id = uuid.uuid4()
    current_user = select(func.current_app_user_id())
    with engine.connect() as connection:
        factory = sessionmaker(bind=connection)
        with user_transaction(factory, user_id) as session:
            assert session.scalar(current_user) == user_id
        with factory.begin() as session:
            assert session.scalar(current_user) is None
