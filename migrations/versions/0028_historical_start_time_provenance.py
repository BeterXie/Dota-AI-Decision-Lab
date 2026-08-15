"""Track whether historical map started_at is estimated.

Revision ID: 0028_historical_start_time_provenance
Revises: 0027_ai_token_usage
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_historical_start_time_provenance"
down_revision: str | None = "0027_ai_token_usage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "historical_maps",
        sa.Column(
            "started_at_estimated",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.alter_column("historical_maps", "started_at_estimated", server_default=None)


def downgrade() -> None:
    op.drop_column("historical_maps", "started_at_estimated")
