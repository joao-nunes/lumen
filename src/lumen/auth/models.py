"""Authentication tables, kept in a separate `auth` Postgres schema.

The schema boundary is deliberate: the application's database role will
get no direct access to `auth.*`, only to narrowly scoped functions (see the
RLS milestone). Constraints here act as a last line of defence against
application bugs, e.g. storing a plaintext password or a raw session token.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from lumen.db.models import Base

AUTH_SCHEMA = "auth"
# Sessions are looked up by SHA-256(token); the digest is always 32 bytes.
SESSION_TOKEN_HASH_BYTES = 32


class PasswordCredential(Base):
    """A user's password, as an Argon2id PHC string.

    The PHC string ($argon2id$v=19$m=...,t=...,p=...$<salt>$<hash>) embeds
    the algorithm, cost parameters, and salt, so there is no separate salt
    column, and hashes can be upgraded on login when parameters change.
    """

    __tablename__ = "password_credentials"
    __table_args__ = (
        CheckConstraint("password_hash LIKE '$argon2id$%'", name="argon2id_hash"),
        {"schema": AUTH_SCHEMA},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # When the password last changed; sessions created before it are invalid.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuthSession(Base):
    """A login session.

    The client holds a random 256-bit token in an HttpOnly cookie; only its
    SHA-256 digest is stored, so a database leak does not leak usable
    sessions. A fast hash is appropriate here (unlike for passwords) because
    the token has full entropy and lookups must be deterministic.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            f"octet_length(token_hash) = {SESSION_TOKEN_HASH_BYTES}", name="token_hash_is_sha256"
        ),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        Index("ix_sessions_user_id", "user_id"),
        Index("ix_sessions_expires_at", "expires_at"),
        {"schema": AUTH_SCHEMA},
    )

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Idle timeout is measured from here; absolute timeout from expires_at.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
