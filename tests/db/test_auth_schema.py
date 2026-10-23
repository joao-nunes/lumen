"""Guarantees the database enforces for authentication data, independently of app code."""

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lumen.auth.models import AuthSession, PasswordCredential
from lumen.db import models
from tests.db.factories import new_user

# Shape of a real argon2-cffi hash; the schema only checks the prefix.
ARGON2ID_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$aGFzaGhhc2hoYXNoaGFzaGhhc2g"
NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def new_token_hash() -> bytes:
    return hashlib.sha256(secrets.token_urlsafe(32).encode()).digest()


def add_session(session: Session, user_id: object, token_hash: bytes, **times: datetime) -> None:
    session.add(
        AuthSession(
            token_hash=token_hash,
            user_id=user_id,
            created_at=times.get("created_at", NOW),
            last_seen_at=times.get("last_seen_at", NOW),
            expires_at=times.get("expires_at", NOW + timedelta(days=7)),
        )
    )
    session.flush()


# --- users.email -------------------------------------------------------------


def test_email_uniqueness_is_case_insensitive(session: Session) -> None:
    new_user(session, "Joao@Example.com")
    with pytest.raises(IntegrityError, match="uq_users_email"):
        new_user(session, "joao@example.com")


def test_email_lookup_is_case_insensitive(session: Session) -> None:
    user_id = new_user(session, "Joao@Example.com")
    found = session.scalar(select(models.User.id).where(models.User.email == "JOAO@EXAMPLE.COM"))
    assert found == user_id


@pytest.mark.parametrize(
    ("email", "constraint"),
    [("not-an-email", "ck_users_email_shape"), ("a" * 250 + "@x.io", "ck_users_email_length")],
)
def test_email_rejects_malformed_values(session: Session, email: str, constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        new_user(session, email)


# --- auth.password_credentials -------------------------------------------------


def test_argon2id_hash_is_accepted(session: Session) -> None:
    user_id = new_user(session)
    session.add(PasswordCredential(user_id=user_id, password_hash=ARGON2ID_HASH))
    session.flush()


@pytest.mark.parametrize(
    "password_hash",
    [
        "correct horse battery staple",  # plaintext
        "$2b$12$abcdefghijklmnopqrstuuABCDEFGHIJKLMNOPQRSTUVWXYZ01234",  # bcrypt
        "$argon2i$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA",  # argon2i, not argon2id
    ],
)
def test_anything_but_argon2id_is_rejected(session: Session, password_hash: str) -> None:
    user_id = new_user(session)
    session.add(PasswordCredential(user_id=user_id, password_hash=password_hash))
    with pytest.raises(IntegrityError, match="ck_password_credentials_argon2id_hash"):
        session.flush()


def test_a_user_has_at_most_one_password(session: Session) -> None:
    user_id = new_user(session)
    session.add(PasswordCredential(user_id=user_id, password_hash=ARGON2ID_HASH))
    session.flush()
    session.expunge_all()
    session.add(PasswordCredential(user_id=user_id, password_hash=ARGON2ID_HASH))
    with pytest.raises(IntegrityError, match="pk_password_credentials"):
        session.flush()


# --- auth.sessions --------------------------------------------------------------


def test_sha256_digest_is_accepted(session: Session) -> None:
    add_session(session, new_user(session), new_token_hash())


def test_raw_token_is_rejected(session: Session) -> None:
    # The cookie value itself (43 URL-safe characters) must never be stored.
    raw_token = secrets.token_urlsafe(32).encode()
    with pytest.raises(IntegrityError, match="ck_sessions_token_hash_is_sha256"):
        add_session(session, new_user(session), raw_token)


def test_session_must_expire_after_creation(session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_sessions_expires_after_created"):
        add_session(session, new_user(session), new_token_hash(), expires_at=NOW)


def test_a_user_can_have_several_sessions(session: Session) -> None:
    user_id = new_user(session)
    add_session(session, user_id, new_token_hash())
    add_session(session, user_id, new_token_hash())
    count = session.scalar(
        select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user_id)
    )
    assert count == 2


# --- lifecycle ------------------------------------------------------------------


def test_deleting_a_user_deletes_their_credentials_and_sessions(session: Session) -> None:
    user_id = new_user(session)
    session.add(PasswordCredential(user_id=user_id, password_hash=ARGON2ID_HASH))
    add_session(session, user_id, new_token_hash())
    session.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})

    for table in (PasswordCredential, AuthSession):
        remaining = session.scalar(
            select(func.count()).select_from(table).where(table.user_id == user_id)
        )
        assert remaining == 0


def test_auth_tables_live_in_the_auth_schema(session: Session) -> None:
    rows = session.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'auth' ORDER BY table_name"
        )
    )
    assert [r[0] for r in rows] == ["password_credentials", "sessions"]
