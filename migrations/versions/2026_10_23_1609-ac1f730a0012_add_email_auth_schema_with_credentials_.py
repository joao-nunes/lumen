"""add email, auth schema with credentials and sessions

Revision ID: ac1f730a0012
Revises: 00355861b0e8
Create Date: 2026-10-23 16:09:20.317956

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "ac1f730a0012"
down_revision: str | Sequence[str] | None = "00355861b0e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Alembic does not manage extensions or schemas; create them explicitly.
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE SCHEMA auth")

    # users.email in three steps, so the migration works on databases that
    # already contain users: add nullable, backfill, then enforce NOT NULL.
    # Placeholders use the reserved .invalid TLD (RFC 2606), so they can
    # never collide with a real address.
    op.add_column("users", sa.Column("email", postgresql.CITEXT(), nullable=True))
    op.execute("UPDATE users SET email = id::text || '@example.invalid' WHERE email IS NULL")
    op.alter_column("users", "email", nullable=False)
    op.create_unique_constraint(op.f("uq_users_email"), "users", ["email"])
    # Autogenerate does not detect check constraints on existing tables.
    op.create_check_constraint(op.f("ck_users_email_shape"), "users", "email LIKE '%_@_%'")
    op.create_check_constraint(op.f("ck_users_email_length"), "users", "char_length(email) <= 254")

    op.create_table(
        "password_credentials",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "password_hash LIKE '$argon2id$%'", name=op.f("ck_password_credentials_argon2id_hash")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_password_credentials_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_password_credentials")),
        schema="auth",
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_sessions_expires_after_created")
        ),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32", name=op.f("ck_sessions_token_hash_is_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_sessions")),
        schema="auth",
    )
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"], schema="auth")
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], schema="auth")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_sessions_user_id", table_name="sessions", schema="auth")
    op.drop_index("ix_sessions_expires_at", table_name="sessions", schema="auth")
    op.drop_table("sessions", schema="auth")
    op.drop_table("password_credentials", schema="auth")
    op.execute("DROP SCHEMA auth")

    op.drop_constraint(op.f("ck_users_email_length"), "users", type_="check")
    op.drop_constraint(op.f("ck_users_email_shape"), "users", type_="check")
    op.drop_constraint(op.f("uq_users_email"), "users", type_="unique")
    op.drop_column("users", "email")
    # citext is left installed: extensions are database-wide and may be used elsewhere.
