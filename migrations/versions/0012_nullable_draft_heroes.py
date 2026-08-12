"""Preserve player slots before heroes are selected.

Revision ID: 0012_nullable_draft_heroes
Revises: 0011_result_evidence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_nullable_draft_heroes"
down_revision: str | None = "0011_result_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "draft_slots",
        "hero_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute("DELETE FROM draft_slots WHERE hero_id IS NULL")
    op.alter_column(
        "draft_slots",
        "hero_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
