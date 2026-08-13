"""Cancel pending AI jobs before the ten-minute decision gate.

Revision ID: 0016_ai_decision_after_ten_minutes
Revises: 0015_ti_provider_identity_repair
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_ai_decision_after_ten_minutes"
down_revision: str | None = "0015_ti_provider_identity_repair"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "postgresql":
        return
    connection.execute(
        sa.text(
            """
            UPDATE durable_jobs AS job
            SET status = 'CANCELLED',
                completed_at = CURRENT_TIMESTAMP,
                locked_by = NULL,
                locked_at = NULL,
                last_error = 'cancelled because AI decisions require game_time_seconds >= 600'
            FROM decision_snapshots AS snapshot
            WHERE job.job_type = 'RUN_AI_PROVIDER'
              AND job.status IN ('PENDING', 'RETRY_WAIT')
              AND job.payload->>'snapshot_id' = snapshot.id::text
              AND (
                  snapshot.canonical_payload->'live' IS NULL
                  OR jsonb_typeof(snapshot.canonical_payload->'live') <> 'object'
                  OR snapshot.canonical_payload->'live'->>'game_time_seconds' IS NULL
                  OR NOT (
                      snapshot.canonical_payload->'live'->>'game_time_seconds'
                  ) ~ '^[0-9]+$'
                  OR (
                      snapshot.canonical_payload->'live'->>'game_time_seconds'
                  )::integer < 600
              )
            """
        )
    )


def downgrade() -> None:
    return None
