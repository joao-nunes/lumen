"""one checkin per local day

Revision ID: 0caa6b3c48a6
Revises: bfba8bd92d55
Create Date: 2026-10-31 15:03:23.021713

Spec 002: saving a day that already has a check-in replaces it. The unique
constraint makes that an upsert target. If a database already holds two
check-ins for one user and day, this upgrade fails rather than guessing which
one to keep; reseed development data in that case.

The constraint's own index covers (user_id, local_date) range queries, so the
plain index on the same columns is dropped.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0caa6b3c48a6"
down_revision: str | Sequence[str] | None = "bfba8bd92d55"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_checkins_user_id_local_date", "checkins", ["user_id", "local_date"]
    )
    op.drop_index("ix_checkins_user_id_local_date", table_name="checkins")


def downgrade() -> None:
    op.create_index("ix_checkins_user_id_local_date", "checkins", ["user_id", "local_date"])
    op.drop_constraint("uq_checkins_user_id_local_date", "checkins", type_="unique")
