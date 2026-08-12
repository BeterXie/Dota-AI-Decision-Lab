"""Version AI experiment identity and clarify odds semantics.

Revision ID: 0009_ai_experiment_identity
Revises: 0008_temporal_calibration_evidence
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_ai_experiment_identity"
down_revision: str | None = "0008_temporal_calibration_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_decisions",
        sa.Column(
            "decision_policy_version",
            sa.String(64),
            nullable=False,
            server_default="shadow-decision-v1",
        ),
    )
    op.drop_constraint("uq_ai_provider_snapshot", "ai_decisions", type_="unique")
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
    op.alter_column("ai_decisions", "decision_policy_version", server_default=None)


def downgrade() -> None:
    op.drop_constraint("uq_ai_experiment", "ai_decisions", type_="unique")
    op.create_unique_constraint(
        "uq_ai_provider_snapshot",
        "ai_decisions",
        ["snapshot_id", "provider"],
    )
    op.drop_column("ai_decisions", "decision_policy_version")
