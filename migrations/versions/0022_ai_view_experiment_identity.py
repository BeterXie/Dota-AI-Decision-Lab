"""Add ai-view version and input hash to AI experiment identity.

Revision ID: 0022_ai_view_experiment_identity
Revises: 0021_dltv_live_canvas_charts_jsonb
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_ai_view_experiment_identity"
down_revision: str | None = "0021_dltv_live_canvas_charts_jsonb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_decisions",
        sa.Column(
            "ai_view_version",
            sa.String(32),
            nullable=False,
            server_default="ai-view-v1",
        ),
    )
    op.add_column("ai_decisions", sa.Column("ai_input_hash", sa.String(64), nullable=True))
    # Pre-v2 records were produced by ai-view-v1 semantics; keep them
    # identified as such so v2 runs become NEW experiments instead of
    # silently reusing views that no longer match the current code.
    op.drop_constraint("uq_ai_experiment", "ai_decisions", type_="unique")
    op.create_unique_constraint(
        "uq_ai_experiment",
        "ai_decisions",
        [
            "snapshot_id",
            "provider",
            "model",
            "prompt_version",
            "decision_policy_version",
            "ai_view_version",
        ],
    )
    op.alter_column("ai_decisions", "ai_view_version", server_default=None)


def downgrade() -> None:
    op.drop_constraint("uq_ai_experiment", "ai_decisions", type_="unique")
    op.drop_column("ai_decisions", "ai_input_hash")
    op.drop_column("ai_decisions", "ai_view_version")
    op.create_unique_constraint(
        "uq_ai_experiment",
        "ai_decisions",
        [
            "snapshot_id",
            "provider",
            "model",
            "prompt_version",
            "decision_policy_version",
        ],
    )
