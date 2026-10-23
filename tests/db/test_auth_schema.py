"""Last-line-of-defence constraints: what the database refuses even if application code is buggy.

Behaviour reachable through the auth service is tested in test_auth_service.py.
"""

import secrets
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lumen.auth.models import AuthSession, PasswordCredential
from tests.db.factories import new_user

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=UTC)


def test_plaintext_password_cannot_be_stored(session: Session) -> None:
    session.add(PasswordCredential(user_id=new_user(session), password_hash="hunter2 hunter2"))
    with pytest.raises(IntegrityError, match="ck_password_credentials_argon2id_hash"):
        session.flush()


def test_raw_session_token_cannot_be_stored(session: Session) -> None:
    raw_token = secrets.token_urlsafe(32).encode()  # the cookie value, not its digest
    session.add(
        AuthSession(
            token_hash=raw_token,
            user_id=new_user(session),
            created_at=NOW,
            last_seen_at=NOW,
            expires_at=NOW + timedelta(days=7),
        )
    )
    with pytest.raises(IntegrityError, match="ck_sessions_token_hash_is_sha256"):
        session.flush()


def test_malformed_email_cannot_be_stored(session: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_users_email_shape"):
        new_user(session, "not-an-email")
