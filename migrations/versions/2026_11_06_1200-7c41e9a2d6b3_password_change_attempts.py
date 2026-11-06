"""password change attempts for rate limiting

Revision ID: 7c41e9a2d6b3
Revises: 0caa6b3c48a6
Create Date: 2026-11-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7c41e9a2d6b3"
down_revision: str | Sequence[str] | None = "0caa6b3c48a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "password_change_attempts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_password_change_attempts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_password_change_attempts")),
        schema="auth",
    )
    op.create_index(
        "ix_password_change_attempts_user_id_attempted_at",
        "password_change_attempts",
        ["user_id", "attempted_at"],
        unique=False,
        schema="auth",
    )
    # Only the auth service records and reads attempts (spec 004 §2.2).
    op.execute("GRANT SELECT, INSERT ON auth.password_change_attempts TO lumen_auth")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_password_change_attempts_user_id_attempted_at",
        table_name="password_change_attempts",
        schema="auth",
    )
    op.drop_table("password_change_attempts", schema="auth")
