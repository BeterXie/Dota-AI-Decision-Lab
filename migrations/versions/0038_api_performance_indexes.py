"""Add indexes used by match, detail, review, and performance projections.

Revision ID: 0038_api_performance_indexes
Revises: 0037_team_roster_registry
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0038_api_performance_indexes"
down_revision: str | None = "0037_team_roster_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_canonical_series_scheduled",
        "canonical_series",
        ["scheduled_at"],
    )
    op.create_index(
        "ix_canonical_map_series_scheduled",
        "canonical_maps",
        ["series_id", "scheduled_at"],
    )
    op.create_index(
        "ix_provider_match_provider_map",
        "provider_match_mappings",
        ["provider", "canonical_map_id"],
    )
    op.create_index(
        "ix_provider_match_provider_series",
        "provider_match_mappings",
        ["provider", "canonical_series_id"],
    )
    op.create_index(
        "ix_odds_map_market_received",
        "odds_observations",
        ["canonical_map_id", "market_type", "received_at"],
    )
    op.create_index(
        "ix_odds_series_market_received",
        "odds_observations",
        ["canonical_series_id", "market_type", "received_at"],
    )
    op.create_index(
        "ix_odds_id_received",
        "odds_observations",
        ["odds_id", "received_at"],
    )
    op.create_index(
        "ix_draft_map_observed",
        "draft_snapshots",
        ["canonical_map_id", "observed_at"],
    )
    op.create_index(
        "ix_ai_snapshot_request",
        "ai_decisions",
        ["snapshot_id", "request_started_at"],
    )
    op.create_index(
        "ix_ai_request_started",
        "ai_decisions",
        ["request_started_at"],
    )
    op.create_index(
        "ix_future_odds_snapshot_capture_status",
        "decision_future_odds",
        ["decision_snapshot_id", "capture_type", "status"],
    )
    op.create_index("ix_map_results_settled", "map_results", ["settled_at"])


def downgrade() -> None:
    op.drop_index("ix_map_results_settled", table_name="map_results")
    op.drop_index(
        "ix_future_odds_snapshot_capture_status",
        table_name="decision_future_odds",
    )
    op.drop_index("ix_ai_request_started", table_name="ai_decisions")
    op.drop_index("ix_ai_snapshot_request", table_name="ai_decisions")
    op.drop_index("ix_draft_map_observed", table_name="draft_snapshots")
    op.drop_index("ix_odds_id_received", table_name="odds_observations")
    op.drop_index("ix_odds_series_market_received", table_name="odds_observations")
    op.drop_index("ix_odds_map_market_received", table_name="odds_observations")
    op.drop_index(
        "ix_provider_match_provider_series",
        table_name="provider_match_mappings",
    )
    op.drop_index("ix_provider_match_provider_map", table_name="provider_match_mappings")
    op.drop_index("ix_canonical_map_series_scheduled", table_name="canonical_maps")
    op.drop_index("ix_canonical_series_scheduled", table_name="canonical_series")
