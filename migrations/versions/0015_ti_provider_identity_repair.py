"""Repair TI provider identity and superseded registry jobs.

Revision ID: 0015_ti_provider_identity_repair
Revises: 0014_resend_email_provider
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_ti_provider_identity_repair"
down_revision: str | None = "0014_resend_email_provider"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    op.add_column(
        "decision_email_notifications",
        sa.Column(
            "translation_status",
            sa.String(32),
            nullable=False,
            server_default="DISABLED",
        ),
    )
    op.add_column(
        "decision_email_notifications",
        sa.Column("translation_model", sa.String(128)),
    )
    op.add_column(
        "decision_email_notifications",
        sa.Column(
            "translation_raw_response",
            sa.JSON().with_variant(
                postgresql.JSONB(astext_type=sa.Text()),
                "postgresql",
            ),
        ),
    )
    op.add_column(
        "decision_email_notifications",
        sa.Column("translation_error", sa.Text()),
    )
    source_team_id = connection.scalar(
        sa.text(
            """
            SELECT canonical_team_id FROM provider_team_mappings
            WHERE provider = 'raybet' AND provider_team_id = '16122'
            """
        )
    )
    target_team_id = connection.scalar(
        sa.text(
            """
            SELECT canonical_team_id FROM provider_team_mappings
            WHERE provider = 'dltv' AND provider_team_id = '7003'
            """
        )
    )
    if (
        source_team_id is not None
        and target_team_id is not None
        and source_team_id != target_team_id
    ):
        _merge_lgd_identity(connection, source_team_id, target_team_id)

    connection.execute(
        sa.text(
            """
            UPDATE durable_jobs
            SET status = 'CANCELLED', completed_at = CURRENT_TIMESTAMP,
                locked_by = NULL, locked_at = NULL,
                last_error = 'superseded after RayBet endpoint recovery'
            WHERE job_type = 'REFRESH_ODDS_REGISTRY'
              AND status IN ('PENDING', 'RETRY_WAIT')
            """
        )
    )


def downgrade() -> None:
    op.drop_column("decision_email_notifications", "translation_error")
    op.drop_column("decision_email_notifications", "translation_raw_response")
    op.drop_column("decision_email_notifications", "translation_model")
    op.drop_column("decision_email_notifications", "translation_status")


def _merge_lgd_identity(connection, source_team_id, target_team_id) -> None:
    source_series = connection.scalar(
        sa.text(
            """
            SELECT canonical_series_id FROM provider_match_mappings
            WHERE provider = 'raybet' AND provider_match_id = '38423248'
            """
        )
    )
    target_series = connection.scalar(
        sa.text(
            """
            SELECT canonical_series_id FROM provider_match_mappings
            WHERE provider = 'dltv' AND provider_match_id = '427635'
            """
        )
    )

    connection.execute(
        sa.text(
            "UPDATE provider_team_mappings SET canonical_team_id = :target "
            "WHERE canonical_team_id = :source"
        ),
        {"source": source_team_id, "target": target_team_id},
    )
    connection.execute(
        sa.text(
            "UPDATE team_aliases SET canonical_team_id = :target WHERE canonical_team_id = :source"
        ),
        {"source": source_team_id, "target": target_team_id},
    )
    team_references = {
        "canonical_series": ("team_a_id", "team_b_id"),
        "odds_observations": ("selection_team_id",),
        "historical_maps": ("radiant_team_id", "dire_team_id", "winner_team_id"),
        "historical_player_maps": ("canonical_team_id", "opponent_team_id"),
        "team_rating_snapshots": ("canonical_team_id",),
        "team_form_snapshots": ("canonical_team_id",),
        "map_results": ("winner_team_id",),
        "map_result_evidence": ("winner_team_id",),
    }
    for table, columns in team_references.items():
        for column in columns:
            connection.execute(
                sa.text(f"UPDATE {table} SET {column} = :target WHERE {column} = :source"),
                {"source": source_team_id, "target": target_team_id},
            )

    if source_series is not None and target_series is not None and source_series != target_series:
        connection.execute(
            sa.text("UPDATE canonical_maps SET series_id = :source WHERE series_id = :target"),
            {"source": source_series, "target": target_series},
        )
        connection.execute(
            sa.text(
                "UPDATE provider_match_mappings SET canonical_series_id = :source "
                "WHERE canonical_series_id = :target"
            ),
            {"source": source_series, "target": target_series},
        )
        connection.execute(
            sa.text(
                "UPDATE odds_observations SET canonical_series_id = :source "
                "WHERE canonical_series_id = :target"
            ),
            {"source": source_series, "target": target_series},
        )
        connection.execute(
            sa.text("DELETE FROM canonical_series WHERE id = :target"),
            {"target": target_series},
        )
    connection.execute(
        sa.text("DELETE FROM canonical_teams WHERE id = :source"),
        {"source": source_team_id},
    )
