import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lumen.auth.models import AuthSession, PasswordCredential
from lumen.db import models
from lumen.db.repository import list_observations, save_checkin
from lumen.domain.checkin import Checkin
from lumen.domain.dimensions import Dimension
from tests.db.factories import new_user

DAY = date(2026, 10, 23)


def make_checkin(day: date = DAY, tags: frozenset[str] = frozenset(), **scores: int) -> Checkin:
    return Checkin(
        recorded_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(hours=21),
        local_date=day,
        scores={Dimension(k): v for k, v in (scores or {"mood": 3}).items()},
        tags=tags,
    )


def test_save_and_list_round_trip(session: Session) -> None:
    user = new_user(session)
    save_checkin(session, user, make_checkin(mood=4, stress=2))

    obs = list_observations(session, user, DAY, DAY)
    assert {(o.dimension, o.value) for o in obs} == {(Dimension.MOOD, 4), (Dimension.STRESS, 2)}


def test_list_observations_respects_date_range(session: Session) -> None:
    user = new_user(session)
    for offset in range(5):
        save_checkin(session, user, make_checkin(DAY + timedelta(days=offset)))

    obs = list_observations(session, user, DAY + timedelta(days=1), DAY + timedelta(days=3))
    assert [o.day for o in obs] == [DAY + timedelta(days=i) for i in (1, 2, 3)]


def test_list_observations_never_returns_other_users_data(session: Session) -> None:
    alice, bob = new_user(session), new_user(session)
    save_checkin(session, alice, make_checkin(mood=5))
    save_checkin(session, bob, make_checkin(mood=1))

    assert [o.value for o in list_observations(session, alice, DAY, DAY)] == [5]
    assert [o.value for o in list_observations(session, bob, DAY, DAY)] == [1]


def test_tags_are_reused_per_user_and_isolated_between_users(session: Session) -> None:
    alice, bob = new_user(session), new_user(session)
    save_checkin(session, alice, make_checkin(tags=frozenset({"exercise"})))
    save_checkin(session, alice, make_checkin(tags=frozenset({"exercise", "alcohol"})))
    save_checkin(session, bob, make_checkin(tags=frozenset({"exercise"})))

    def tag_names(user: uuid.UUID) -> list[str]:
        return list(
            session.scalars(
                select(models.Tag.name).where(models.Tag.user_id == user).order_by(models.Tag.name)
            )
        )

    assert tag_names(alice) == ["alcohol", "exercise"]
    assert tag_names(bob) == ["exercise"]


def test_database_rejects_out_of_scale_scores(session: Session) -> None:
    user = new_user(session)
    checkin_id = save_checkin(session, user, make_checkin())
    with pytest.raises(IntegrityError, match="value_in_scale"):
        session.execute(
            text(
                "INSERT INTO checkin_scores (checkin_id, user_id, dimension, value) "
                "VALUES (:c, :u, 'energy', 6)"
            ),
            {"c": checkin_id, "u": user},
        )


def test_composite_foreign_key_prevents_linking_another_users_tag(session: Session) -> None:
    alice, bob = new_user(session), new_user(session)
    alice_checkin = save_checkin(session, alice, make_checkin())
    save_checkin(session, bob, make_checkin(tags=frozenset({"exercise"})))
    bob_tag = session.scalar(select(models.Tag.id).where(models.Tag.user_id == bob))

    with pytest.raises(IntegrityError, match="fk_checkin_tags_tag_id_user_id_tags"):
        session.execute(
            text("INSERT INTO checkin_tags (checkin_id, tag_id, user_id) VALUES (:c, :t, :u)"),
            {"c": alice_checkin, "t": bob_tag, "u": alice},
        )


def test_deleting_a_user_deletes_all_their_data(session: Session) -> None:
    user = new_user(session)
    save_checkin(session, user, make_checkin(tags=frozenset({"exercise"}), mood=3, energy=3))
    session.add(
        PasswordCredential(user_id=user, password_hash="$argon2id$v=19$m=8,t=1,p=1$c2FsdA$aGFzaA")
    )
    session.add(
        AuthSession(
            token_hash=bytes(32),
            user_id=user,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            last_seen_at=datetime(2026, 1, 1, tzinfo=UTC),
            expires_at=datetime(2026, 1, 8, tzinfo=UTC),
        )
    )
    session.flush()
    session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user})

    for table in (
        models.Checkin,
        models.CheckinScore,
        models.Tag,
        models.CheckinTag,
        PasswordCredential,
        AuthSession,
    ):
        assert (
            session.scalar(select(func.count()).select_from(table).where(table.user_id == user))
            == 0
        )
