"""Add provider token/cache usage telemetry to AI decisions.

Revision ID: 0027_ai_token_usage
Revises: 0026_ai_latency_trace
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_ai_token_usage"
down_revision: str | None = "0026_ai_latency_trace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in (
        "input_tokens",
        "cached_input_tokens",
        "reasoning_tokens",
        "output_tokens",
        "total_tokens",
    ):
        op.add_column("ai_decisions", sa.Column(column, sa.Integer(), nullable=True))


def downgrade() -> None:
    for column in (
        "total_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cached_input_tokens",
        "input_tokens",
    ):
        op.drop_column("ai_decisions", column)
