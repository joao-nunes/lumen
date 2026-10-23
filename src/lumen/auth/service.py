"""Registration, login, session resolution, logout, and password changes.

Every operation takes the current time explicitly (`now`), so expiry logic is
deterministic and testable, and a single clock decides all timestamps.

The service never commits; the caller owns the transaction.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from lumen.auth.models import AuthSession, PasswordCredential
from lumen.auth.passwords import Passwords, check_policy
from lumen.auth.policy import SessionPolicy
from lumen.auth.tokens import hash_token, is_well_formed, new_token
from lumen.db.models import User
from lumen.db.repository import create_user

MAX_EMAIL_LENGTH = 254


class AuthError(Exception):
    pass


class InvalidEmailError(AuthError):
    pass


class EmailTakenError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    """Deliberately generic: never says whether the email or the password was wrong."""

    def __init__(self) -> None:
        super().__init__("Invalid email or password")


@dataclass(frozen=True, slots=True)
class IssuedSession:
    user_id: uuid.UUID
    # The raw token for the cookie. It exists only here and in the client.
    token: str
    expires_at: datetime


def normalize_email(email: str) -> str:
    """Trim and sanity-check. Case is preserved; citext makes comparisons case-insensitive."""
    email = email.strip()
    local, sep, domain = email.partition("@")
    if not sep or not local or not domain or "@" in domain or len(email) > MAX_EMAIL_LENGTH:
        raise InvalidEmailError("Invalid email address")
    return email


def _require_aware(now: datetime) -> None:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")


class AuthService:
    def __init__(
        self, passwords: Passwords | None = None, policy: SessionPolicy | None = None
    ) -> None:
        self.passwords = passwords or Passwords()
        self.policy = policy or SessionPolicy()

    def register(self, db: Session, email: str, password: str) -> uuid.UUID:
        email = normalize_email(email)
        check_policy(password, email=email)
        password_hash = self.passwords.hash(password)
        try:
            # The savepoint lets a duplicate email fail without aborting the
            # caller's transaction. Relying on the unique constraint (rather
            # than checking first) is also race-free.
            with db.begin_nested():
                user_id = create_user(db, email)
        except IntegrityError as exc:
            if "uq_users_email" in str(exc.orig):
                raise EmailTakenError("An account with this email already exists") from exc
            raise
        db.add(PasswordCredential(user_id=user_id, password_hash=password_hash))
        db.flush()
        return user_id

    def login(self, db: Session, email: str, password: str, now: datetime) -> IssuedSession:
        _require_aware(now)
        try:
            email = normalize_email(email)
        except InvalidEmailError:
            self.passwords.verify_dummy(password)
            raise InvalidCredentialsError() from None

        row = db.execute(
            select(User.id, PasswordCredential.password_hash)
            .join(PasswordCredential, PasswordCredential.user_id == User.id)
            .where(User.email == email)
        ).one_or_none()
        if row is None:
            # Same cost as a real verification, so timing doesn't reveal the account exists.
            self.passwords.verify_dummy(password)
            raise InvalidCredentialsError()

        user_id, stored_hash = row
        result = self.passwords.verify(stored_hash, password)
        if not result.valid:
            raise InvalidCredentialsError()
        if result.needs_rehash:
            # Upgrade the hash to current parameters. This is not a password
            # change, so updated_at is explicitly kept as it was.
            db.execute(
                update(PasswordCredential)
                .where(PasswordCredential.user_id == user_id)
                .values(
                    password_hash=self.passwords.hash(password),
                    updated_at=PasswordCredential.updated_at,
                )
            )
        # Always a brand-new session on login (session rotation). The web
        # layer must discard any session cookie the client already had.
        return self._issue(db, user_id, now)

    def resolve(self, db: Session, token: str, now: datetime) -> uuid.UUID | None:
        """The user a session token belongs to, or None if invalid or expired."""
        _require_aware(now)
        if not is_well_formed(token):
            return None
        session = db.get(AuthSession, hash_token(token))
        if session is None:
            return None
        if now >= session.expires_at or now >= session.last_seen_at + self.policy.idle_timeout:
            db.delete(session)
            db.flush()
            return None
        if now - session.last_seen_at >= self.policy.touch_interval:
            session.last_seen_at = now
            db.flush()
        return session.user_id

    def logout(self, db: Session, token: str) -> None:
        if is_well_formed(token):
            db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))

    def change_password(
        self,
        db: Session,
        user_id: uuid.UUID,
        current_password: str,
        new_password: str,
        now: datetime,
    ) -> IssuedSession:
        """Change the password, end every existing session, and issue a fresh one."""
        _require_aware(now)
        credential = db.get(PasswordCredential, user_id)
        user = db.get(User, user_id)
        if credential is None or user is None:
            raise InvalidCredentialsError()
        if not self.passwords.verify(credential.password_hash, current_password).valid:
            raise InvalidCredentialsError()
        check_policy(new_password, email=user.email)

        credential.password_hash = self.passwords.hash(new_password)
        credential.updated_at = now
        # A stolen session must not survive a password change.
        self.revoke_all_sessions(db, user_id)
        return self._issue(db, user_id, now)

    def revoke_all_sessions(self, db: Session, user_id: uuid.UUID) -> int:
        result = db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
        return int(result.rowcount)  # type: ignore[attr-defined]

    def purge_expired(self, db: Session, now: datetime) -> int:
        """Delete sessions past either timeout. Intended for a scheduled job."""
        _require_aware(now)
        result = db.execute(
            delete(AuthSession).where(
                or_(
                    AuthSession.expires_at <= now,
                    AuthSession.last_seen_at <= now - self.policy.idle_timeout,
                )
            )
        )
        return int(result.rowcount)  # type: ignore[attr-defined]

    def _issue(self, db: Session, user_id: uuid.UUID, now: datetime) -> IssuedSession:
        token = new_token()
        expires_at = now + self.policy.absolute_timeout
        db.add(
            AuthSession(
                token_hash=hash_token(token),
                user_id=user_id,
                created_at=now,
                last_seen_at=now,
                expires_at=expires_at,
            )
        )
        db.flush()
        return IssuedSession(user_id=user_id, token=token, expires_at=expires_at)
