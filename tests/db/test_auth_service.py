"""Auth service behaviour against a real database, with a controlled clock."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from argon2 import PasswordHasher
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from lumen.auth.models import AuthSession, PasswordCredential
from lumen.auth.passwords import PasswordPolicyError, Passwords
from lumen.auth.policy import SessionPolicy
from lumen.auth.service import (
    AuthService,
    EmailTakenError,
    InvalidCredentialsError,
    InvalidEmailError,
)
from lumen.auth.tokens import hash_token
from lumen.db.models import User

T0 = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
EMAIL = "joao@example.com"
PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "purple elephant dancing slowly"


@pytest.fixture
def auth(passwords: Passwords) -> AuthService:
    return AuthService(passwords=passwords, policy=SessionPolicy())


@pytest.fixture
def user_id(auth: AuthService, session: Session) -> object:
    return auth.register(session, EMAIL, PASSWORD)


def session_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(AuthSession)) or 0


# --- register -------------------------------------------------------------------


def test_register_stores_an_argon2id_hash_not_the_password(
    auth: AuthService, session: Session
) -> None:
    user_id = auth.register(session, EMAIL, PASSWORD)
    stored = session.get(PasswordCredential, user_id)
    assert stored is not None
    assert stored.password_hash.startswith("$argon2id$")
    assert PASSWORD not in stored.password_hash


def test_register_rejects_duplicate_email_regardless_of_case(
    auth: AuthService, session: Session
) -> None:
    auth.register(session, EMAIL, PASSWORD)
    with pytest.raises(EmailTakenError):
        auth.register(session, EMAIL.upper(), PASSWORD)
    # The failed attempt must not break the surrounding transaction.
    auth.register(session, "other@example.com", PASSWORD)


def test_register_enforces_password_policy_before_creating_anything(
    auth: AuthService, session: Session
) -> None:
    with pytest.raises(PasswordPolicyError):
        auth.register(session, EMAIL, "too short")
    assert session.scalar(select(func.count()).select_from(User)) == 0


def test_register_rejects_invalid_email(auth: AuthService, session: Session) -> None:
    for email in ("no-at-sign", "a@b@c"):
        with pytest.raises(InvalidEmailError):
            auth.register(session, email, PASSWORD)


# --- login ----------------------------------------------------------------------


def test_login_issues_a_session_that_resolves_to_the_user(
    auth: AuthService, session: Session, user_id: object
) -> None:
    issued = auth.login(session, EMAIL, PASSWORD, T0)
    assert issued.user_id == user_id
    assert issued.expires_at == T0 + timedelta(days=7)
    assert auth.resolve(session, issued.token, T0) == user_id


def test_login_email_is_case_insensitive_and_trimmed(
    auth: AuthService, session: Session, user_id: object
) -> None:
    assert auth.login(session, "  JOAO@Example.COM ", PASSWORD, T0).user_id == user_id


def test_only_the_token_hash_is_stored(
    auth: AuthService, session: Session, user_id: object
) -> None:
    issued = auth.login(session, EMAIL, PASSWORD, T0)
    stored = session.scalars(select(AuthSession.token_hash)).all()
    assert stored == [hash_token(issued.token)]
    assert issued.token.encode() not in stored


def test_every_login_creates_a_new_session(
    auth: AuthService, session: Session, user_id: object
) -> None:
    first = auth.login(session, EMAIL, PASSWORD, T0)
    second = auth.login(session, EMAIL, PASSWORD, T0)
    assert first.token != second.token
    assert session_count(session) == 2


@pytest.mark.parametrize(
    ("email", "password"),
    [(EMAIL, "wrong password entirely"), ("nobody@example.com", PASSWORD), ("bad", PASSWORD)],
)
def test_failed_logins_give_the_same_generic_error(
    auth: AuthService, session: Session, user_id: object, email: str, password: str
) -> None:
    with pytest.raises(InvalidCredentialsError, match=r"^Invalid email or password$"):
        auth.login(session, email, password, T0)
    assert session_count(session) == 0


def test_unknown_email_still_spends_a_password_verification(
    auth: AuthService, session: Session
) -> None:
    with (
        patch.object(auth.passwords, "verify_dummy", wraps=auth.passwords.verify_dummy) as dummy,
        pytest.raises(InvalidCredentialsError),
    ):
        auth.login(session, "nobody@example.com", PASSWORD, T0)
    dummy.assert_called_once()


def test_login_upgrades_outdated_hash_without_marking_a_password_change(
    session: Session,
) -> None:
    weak = AuthService(Passwords(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)))
    strong = AuthService(Passwords(PasswordHasher(time_cost=2, memory_cost=16, parallelism=1)))
    user_id = weak.register(session, EMAIL, PASSWORD)
    before = session.get(PasswordCredential, user_id)
    assert before is not None
    # Backdate: Postgres now() is the transaction start time, so without this
    # an accidental "updated_at = now()" would be indistinguishable here.
    before.updated_at = T0 - timedelta(days=30)
    session.flush()
    old_hash, old_updated_at = before.password_hash, before.updated_at

    strong.login(session, EMAIL, PASSWORD, T0)
    session.expire_all()
    after = session.get(PasswordCredential, user_id)
    assert after is not None
    assert after.password_hash != old_hash
    assert "m=16,t=2" in after.password_hash
    assert after.updated_at == old_updated_at


# --- resolve and expiry -----------------------------------------------------------


def test_resolve_rejects_malformed_and_unknown_tokens(auth: AuthService, session: Session) -> None:
    assert auth.resolve(session, "not-a-token", T0) is None
    assert auth.resolve(session, "x" * 43, T0) is None  # well-formed but unknown


def test_idle_timeout(auth: AuthService, session: Session, user_id: object) -> None:
    token = auth.login(session, EMAIL, PASSWORD, T0).token
    assert auth.resolve(session, token, T0 + timedelta(hours=11, minutes=59)) == user_id
    # Last activity was at 11:59; idle expiry is 12h after that.
    assert auth.resolve(session, token, T0 + timedelta(hours=23, minutes=58)) == user_id
    assert auth.resolve(session, token, T0 + timedelta(hours=35, minutes=58)) is None
    assert session_count(session) == 0  # expired sessions are deleted on contact


def test_absolute_timeout_applies_even_to_active_sessions(
    auth: AuthService, session: Session, user_id: object
) -> None:
    token = auth.login(session, EMAIL, PASSWORD, T0).token
    t = T0
    while t < T0 + timedelta(days=7) - timedelta(hours=6):
        t += timedelta(hours=6)  # active every 6h, never idle
        assert auth.resolve(session, token, t) == user_id
    assert auth.resolve(session, token, T0 + timedelta(days=7)) is None


def test_last_seen_is_only_written_after_the_touch_interval(
    auth: AuthService, session: Session, user_id: object
) -> None:
    token = auth.login(session, EMAIL, PASSWORD, T0).token
    stored = session.get(AuthSession, hash_token(token))
    assert stored is not None

    auth.resolve(session, token, T0 + timedelta(minutes=4))
    assert stored.last_seen_at == T0
    auth.resolve(session, token, T0 + timedelta(minutes=5))
    assert stored.last_seen_at == T0 + timedelta(minutes=5)


# --- logout -----------------------------------------------------------------------


def test_logout_ends_only_that_session(
    auth: AuthService, session: Session, user_id: object
) -> None:
    laptop = auth.login(session, EMAIL, PASSWORD, T0).token
    desktop = auth.login(session, EMAIL, PASSWORD, T0).token
    auth.logout(session, laptop)
    assert auth.resolve(session, laptop, T0) is None
    assert auth.resolve(session, desktop, T0) == user_id


# --- change password --------------------------------------------------------------


def test_change_password_ends_all_sessions_and_issues_a_new_one(
    auth: AuthService, session: Session, user_id: object
) -> None:
    old_sessions = [auth.login(session, EMAIL, PASSWORD, T0).token for _ in range(2)]
    later = T0 + timedelta(hours=1)
    issued = auth.change_password(session, user_id, PASSWORD, NEW_PASSWORD, later)  # type: ignore[arg-type]

    assert all(auth.resolve(session, t, later) is None for t in old_sessions)
    assert auth.resolve(session, issued.token, later) == user_id
    assert auth.login(session, EMAIL, NEW_PASSWORD, later).user_id == user_id
    with pytest.raises(InvalidCredentialsError):
        auth.login(session, EMAIL, PASSWORD, later)
    credential = session.get(PasswordCredential, user_id)
    assert credential is not None
    assert credential.updated_at == later  # records when the password changed


def test_change_password_requires_the_current_password(
    auth: AuthService, session: Session, user_id: object
) -> None:
    token = auth.login(session, EMAIL, PASSWORD, T0).token
    with pytest.raises(InvalidCredentialsError):
        auth.change_password(session, user_id, "not my password", NEW_PASSWORD, T0)  # type: ignore[arg-type]
    assert auth.resolve(session, token, T0) == user_id  # nothing was revoked


def test_change_password_enforces_policy(
    auth: AuthService, session: Session, user_id: object
) -> None:
    with pytest.raises(PasswordPolicyError):
        auth.change_password(session, user_id, PASSWORD, "short", T0)  # type: ignore[arg-type]


# --- purge ------------------------------------------------------------------------


def test_purge_removes_idle_and_absolute_expired_sessions_only(
    auth: AuthService, session: Session, user_id: object
) -> None:
    idle = auth.login(session, EMAIL, PASSWORD, T0).token
    active = auth.login(session, EMAIL, PASSWORD, T0).token
    now = T0 + timedelta(hours=13)
    stored = session.get(AuthSession, hash_token(active))
    assert stored is not None
    stored.last_seen_at = now - timedelta(minutes=1)
    session.flush()

    assert auth.purge_expired(session, now) == 1
    assert session.get(AuthSession, hash_token(idle)) is None
    assert session.get(AuthSession, hash_token(active)) is not None
    assert auth.purge_expired(session, T0 + timedelta(days=7)) == 1
    assert session_count(session) == 0
