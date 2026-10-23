"""Auth service behaviour against a real database, with a controlled clock."""

import statistics
import time
from datetime import UTC, datetime, timedelta

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


def test_register_rejects_duplicate_email_regardless_of_case(
    auth: AuthService, session: Session
) -> None:
    auth.register(session, EMAIL, PASSWORD)
    with pytest.raises(EmailTakenError):
        auth.register(session, EMAIL.upper(), PASSWORD)
    # The failed attempt must not break the surrounding transaction.
    auth.register(session, "other@example.com", PASSWORD)


def test_register_rejects_weak_password_or_invalid_email_without_creating_a_user(
    auth: AuthService, session: Session
) -> None:
    for email, password, error in [
        (EMAIL, "too short", PasswordPolicyError),
        ("no-at-sign", PASSWORD, InvalidEmailError),
        ("a@b@c", PASSWORD, InvalidEmailError),
    ]:
        with pytest.raises(error):
            auth.register(session, email, password)
    assert session.scalar(select(func.count()).select_from(User)) == 0


# --- login ----------------------------------------------------------------------


def test_every_login_issues_a_new_session_and_email_case_is_ignored(
    auth: AuthService, session: Session, user_id: object
) -> None:
    first = auth.login(session, "  JOAO@Example.COM ", PASSWORD, T0)
    second = auth.login(session, EMAIL, PASSWORD, T0)
    assert first.token != second.token
    assert (
        first.expires_at,
        auth.resolve(session, first.token, T0),
        auth.resolve(session, second.token, T0),
    ) == (T0 + timedelta(days=7), user_id, user_id)


@pytest.mark.parametrize(
    ("email", "password"),
    [(EMAIL, "wrong password entirely"), ("nobody@example.com", PASSWORD), ("bad", PASSWORD)],
)
def test_failed_logins_give_the_same_generic_error_and_no_session(
    auth: AuthService, session: Session, user_id: object, email: str, password: str
) -> None:
    with pytest.raises(InvalidCredentialsError, match=r"^Invalid email or password$"):
        auth.login(session, email, password, T0)
    assert session_count(session) == 0


def test_unknown_email_takes_as_long_as_a_wrong_password(session: Session) -> None:
    # Production hashing parameters (~30 ms per hash), so timing is dominated by
    # hashing, not the database: without the dummy verification an unknown
    # email answers ~30x faster and reveals which accounts exist.
    auth = AuthService()
    auth.register(session, EMAIL, PASSWORD)

    def median_seconds(email: str, password: str) -> float:
        samples = []
        for _ in range(3):
            start = time.perf_counter()
            with pytest.raises(InvalidCredentialsError):
                auth.login(session, email, password, T0)
            samples.append(time.perf_counter() - start)
        return statistics.median(samples)

    wrong_password = median_seconds(EMAIL, "wrong password entirely")
    unknown_email = median_seconds("nobody@example.com", PASSWORD)
    assert unknown_email > 0.5 * wrong_password


def test_login_upgrades_outdated_hash_without_marking_a_password_change(
    session: Session,
) -> None:
    weak = AuthService(Passwords(PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)))
    strong = AuthService(Passwords(PasswordHasher(time_cost=2, memory_cost=16, parallelism=1)))
    user_id = weak.register(session, EMAIL, PASSWORD)
    credential = session.get(PasswordCredential, user_id)
    assert credential is not None
    # Backdate: Postgres now() is the transaction start time, so without this
    # an accidental "updated_at = now()" would be indistinguishable here.
    credential.updated_at = T0 - timedelta(days=30)
    session.flush()

    strong.login(session, EMAIL, PASSWORD, T0)
    session.expire_all()
    credential = session.get(PasswordCredential, user_id)
    assert credential is not None
    assert ("m=16,t=2" in credential.password_hash, credential.updated_at) == (
        True,
        T0 - timedelta(days=30),
    )


# --- session expiry ---------------------------------------------------------------


def test_idle_timeout_expires_and_deletes_unused_sessions(
    auth: AuthService, session: Session, user_id: object
) -> None:
    token = auth.login(session, EMAIL, PASSWORD, T0).token
    assert auth.resolve(session, token, T0 + timedelta(hours=11, minutes=59)) == user_id
    # Last activity was at 11:59; idle expiry is 12h after that.
    assert auth.resolve(session, token, T0 + timedelta(hours=23, minutes=58)) == user_id
    assert auth.resolve(session, token, T0 + timedelta(hours=35, minutes=58)) is None
    assert session_count(session) == 0


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
    assert (
        session.get(AuthSession, hash_token(idle)),
        session.get(AuthSession, hash_token(active)) is not None,
    ) == (None, True)
    assert auth.purge_expired(session, T0 + timedelta(days=7)) == 1


# --- logout and password change -----------------------------------------------


def test_logout_ends_only_that_session(
    auth: AuthService, session: Session, user_id: object
) -> None:
    laptop = auth.login(session, EMAIL, PASSWORD, T0).token
    desktop = auth.login(session, EMAIL, PASSWORD, T0).token
    auth.logout(session, laptop)
    assert (auth.resolve(session, laptop, T0), auth.resolve(session, desktop, T0)) == (
        None,
        user_id,
    )


def test_change_password_ends_all_sessions_and_issues_a_new_one(
    auth: AuthService, session: Session, user_id: object
) -> None:
    old_sessions = [auth.login(session, EMAIL, PASSWORD, T0).token for _ in range(2)]
    later = T0 + timedelta(hours=1)
    issued = auth.change_password(session, user_id, PASSWORD, NEW_PASSWORD, later)  # type: ignore[arg-type]

    assert [auth.resolve(session, t, later) for t in old_sessions] == [None, None]
    assert auth.resolve(session, issued.token, later) == user_id
    assert auth.login(session, EMAIL, NEW_PASSWORD, later).user_id == user_id
    with pytest.raises(InvalidCredentialsError):
        auth.login(session, EMAIL, PASSWORD, later)
    credential = session.get(PasswordCredential, user_id)
    assert credential is not None
    assert credential.updated_at == later


@pytest.mark.parametrize(
    ("current", "new", "error"),
    [
        ("not my password", NEW_PASSWORD, InvalidCredentialsError),
        (PASSWORD, "short", PasswordPolicyError),
    ],
)
def test_rejected_password_change_revokes_nothing(
    auth: AuthService,
    session: Session,
    user_id: object,
    current: str,
    new: str,
    error: type[Exception],
) -> None:
    token = auth.login(session, EMAIL, PASSWORD, T0).token
    with pytest.raises(error):
        auth.change_password(session, user_id, current, new, T0)  # type: ignore[arg-type]
    assert auth.resolve(session, token, T0) == user_id
