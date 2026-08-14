"""Align canvas/charts columns to the ORM JSONB variant on existing databases.

Revision ID: 0021_dltv_live_canvas_charts_jsonb
Revises: 0020_dltv_live_canvas_charts
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021_dltv_live_canvas_charts_jsonb"
down_revision: str | None = "0020_dltv_live_canvas_charts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON_DOCUMENT = sa.JSON().with_variant(sa.dialects.postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    for column in ("canvas", "charts"):
        op.alter_column(
            "dltv_live_observations",
            column,
            type_=JSON_DOCUMENT,
            postgresql_using=f"{column}::jsonb",
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    for column in ("canvas", "charts"):
        op.alter_column(
            "dltv_live_observations",
            column,
            type_=sa.JSON(),
            postgresql_using=f"{column}::json",
        )
