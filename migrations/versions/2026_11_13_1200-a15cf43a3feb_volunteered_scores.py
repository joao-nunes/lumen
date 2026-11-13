"""volunteered scores (spec 008)

Revision ID: a15cf43a3feb
Revises: 7c41e9a2d6b3
Create Date: 2026-11-13 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a15cf43a3feb"
down_revision: str | Sequence[str] | None = "7c41e9a2d6b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The schedule as it was when this migration was written (`dimensions_for` in
# lumen.domain.dimensions), copied here so later changes to it can't change what this does.
# Each day asks two of the four rotating dimensions, in the order of the array below,
# starting at (ordinal * 2) % 4, where Python's date.toordinal() counts 1 for 0001-01-01.
LABEL_EXISTING = """
UPDATE checkin_scores AS s
SET volunteered = true
FROM checkins AS c
WHERE c.id = s.checkin_id
  AND c.user_id = s.user_id
  AND array_position(
        ARRAY['sleep_quality', 'motivation', 'concentration', 'social_connection'],
        s.dimension::text
      ) IS NOT NULL
  AND (array_position(
         ARRAY['sleep_quality', 'motivation', 'concentration', 'social_connection'],
         s.dimension::text
       ) - 1 - ((c.local_date - DATE '0001-01-01' + 1) * 2) % 4 + 4) % 4 >= 2
"""


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "checkin_scores",
        sa.Column("volunteered", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.execute(LABEL_EXISTING)
    # No default from here on: every new score must say whether it was asked.
    op.alter_column("checkin_scores", "volunteered", server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("checkin_scores", "volunteered")
