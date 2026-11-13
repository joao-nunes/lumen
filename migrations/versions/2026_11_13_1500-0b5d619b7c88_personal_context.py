"""personal context (spec 010)

Revision ID: 0b5d619b7c88
Revises: a15cf43a3feb
Create Date: 2026-11-13 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0b5d619b7c88"
down_revision: str | Sequence[str] | None = "a15cf43a3feb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "lumen_app"


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "personal_context",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "char_length(text) BETWEEN 1 AND 750",
            name=op.f("ck_personal_context_text_length"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_personal_context_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_personal_context")),
    )
    # User data: forced RLS and explicit grants, as for every user-data table (CLAUDE.md).
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON personal_context TO {APP_ROLE}")
    op.execute("ALTER TABLE personal_context ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE personal_context FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY user_isolation ON personal_context TO {APP_ROLE}
        USING (user_id = (SELECT current_app_user_id()))
        WITH CHECK (user_id = (SELECT current_app_user_id()))
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("personal_context")
