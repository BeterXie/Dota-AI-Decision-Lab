"""Version AI experiments and shadow portfolios by execution configuration.

Revision ID: 0042_ai_execution_config_version
Revises: 0038_runtime_configuration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0042_ai_execution_config_version"
down_revision: str | None = "0038_runtime_configuration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATIC_VERSION = "static-v1"

_RECOMPUTE_PORTFOLIOS_SQL = """
WITH ordered AS (
    SELECT
        id,
        SUM(cash_delta) OVER (
            PARTITION BY portfolio_account_id
            ORDER BY
                occurred_at,
                CASE entry_type
                    WHEN 'EVENT_FUNDED' THEN 0
                    WHEN 'BET_PLACED' THEN 1
                    ELSE 2
                END,
                id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS computed_cash_after,
        SUM(locked_delta) OVER (
            PARTITION BY portfolio_account_id
            ORDER BY
                occurred_at,
                CASE entry_type
                    WHEN 'EVENT_FUNDED' THEN 0
                    WHEN 'BET_PLACED' THEN 1
                    ELSE 2
                END,
                id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS computed_locked_after
    FROM ai_tournament_ledger
)
UPDATE ai_tournament_ledger AS ledger
SET
    cash_after = ordered.computed_cash_after,
    locked_after = ordered.computed_locked_after,
    equity_after = ordered.computed_cash_after + ordered.computed_locked_after
FROM ordered
WHERE ordered.id = ledger.id;

UPDATE ai_tournament_positions AS position
SET cash_before = placed.cash_after - placed.cash_delta
FROM ai_tournament_ledger AS placed
WHERE
    placed.position_id = position.id
    AND placed.entry_type = 'BET_PLACED';

UPDATE ai_tournament_positions AS position
SET cash_before = COALESCE(
    (
        SELECT ledger.cash_after
        FROM ai_tournament_ledger AS ledger
        WHERE
            ledger.portfolio_account_id = position.portfolio_account_id
            AND ledger.occurred_at <= position.opened_at
        ORDER BY
            ledger.occurred_at DESC,
            CASE ledger.entry_type
                WHEN 'EVENT_FUNDED' THEN 0
                WHEN 'BET_PLACED' THEN 1
                ELSE 2
            END DESC,
            ledger.id DESC
        LIMIT 1
    ),
    account.initial_bankroll
)
FROM ai_tournament_portfolios AS account
WHERE
    account.id = position.portfolio_account_id
    AND NOT EXISTS (
        SELECT 1
        FROM ai_tournament_ledger AS placed
        WHERE
            placed.position_id = position.id
            AND placed.entry_type = 'BET_PLACED'
    );

WITH timeline AS (
    SELECT
        portfolio_account_id,
        equity_after,
        MAX(equity_after) OVER (
            PARTITION BY portfolio_account_id
            ORDER BY
                occurred_at,
                CASE entry_type
                    WHEN 'EVENT_FUNDED' THEN 0
                    WHEN 'BET_PLACED' THEN 1
                    ELSE 2
                END,
                id
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS running_peak
    FROM ai_tournament_ledger
),
risk AS (
    SELECT
        portfolio_account_id,
        MAX(running_peak) AS peak_equity,
        MAX(running_peak - equity_after) AS max_drawdown,
        MAX(
            CASE
                WHEN running_peak > 0
                THEN (running_peak - equity_after) / running_peak
                ELSE 0
            END
        ) AS max_drawdown_pct
    FROM timeline
    GROUP BY portfolio_account_id
),
final_balance AS (
    SELECT DISTINCT ON (portfolio_account_id)
        portfolio_account_id,
        cash_after,
        locked_after
    FROM ai_tournament_ledger
    ORDER BY
        portfolio_account_id,
        occurred_at DESC,
        CASE entry_type
            WHEN 'EVENT_FUNDED' THEN 0
            WHEN 'BET_PLACED' THEN 1
            ELSE 2
        END DESC,
        id DESC
),
totals AS (
    SELECT
        portfolio_account_id,
        SUM(realized_pnl_delta) AS realized_pnl,
        MAX(occurred_at) AS last_occurred_at
    FROM ai_tournament_ledger
    GROUP BY portfolio_account_id
)
UPDATE ai_tournament_portfolios AS account
SET
    cash_balance = final_balance.cash_after,
    locked_balance = final_balance.locked_after,
    realized_pnl = totals.realized_pnl,
    peak_equity = risk.peak_equity,
    max_drawdown = risk.max_drawdown,
    max_drawdown_pct = risk.max_drawdown_pct,
    status = CASE
        WHEN final_balance.cash_after <= 0 AND final_balance.locked_after <= 0
        THEN 'BANKRUPT'
        ELSE 'ACTIVE'
    END,
    updated_at = GREATEST(account.updated_at, totals.last_occurred_at)
FROM final_balance, totals, risk
WHERE
    final_balance.portfolio_account_id = account.id
    AND totals.portfolio_account_id = account.id
    AND risk.portfolio_account_id = account.id;
"""


def _recompute_portfolios() -> None:
    statements = _RECOMPUTE_PORTFOLIOS_SQL.strip().removesuffix(";").split(";\n\n")
    for statement in statements:
        op.execute(statement)


def upgrade() -> None:
    op.add_column(
        "ai_decisions",
        sa.Column("execution_config_version", sa.String(length=128), nullable=True),
    )
    op.execute(
        f"""
        UPDATE ai_decisions
        SET execution_config_version = COALESCE(
            NULLIF(substring(model_version from '@cfg:([^@]+)$'), ''),
            '{_STATIC_VERSION}'
        )
        """
    )
    op.alter_column("ai_decisions", "execution_config_version", nullable=False)
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
            "execution_config_version",
        ],
    )

    op.add_column(
        "ai_tournament_portfolios",
        sa.Column("execution_config_version", sa.String(length=128), nullable=True),
    )
    op.drop_constraint(
        "uq_ai_tournament_portfolio_experiment",
        "ai_tournament_portfolios",
        type_="unique",
    )

    op.execute(
        f"""
        CREATE TEMPORARY TABLE _portfolio_execution_targets ON COMMIT DROP AS
        WITH positioned AS (
            SELECT
                account.id AS old_account_id,
                decision.execution_config_version,
                MIN(position.opened_at) AS first_observed_at
            FROM ai_tournament_portfolios AS account
            JOIN ai_tournament_positions AS position
                ON position.portfolio_account_id = account.id
            JOIN ai_decisions AS decision
                ON decision.id = position.ai_decision_id
            GROUP BY account.id, decision.execution_config_version
        ),
        unpositioned AS (
            SELECT
                account.id AS old_account_id,
                '{_STATIC_VERSION}'::varchar AS execution_config_version,
                account.created_at AS first_observed_at
            FROM ai_tournament_portfolios AS account
            WHERE NOT EXISTS (
                SELECT 1
                FROM ai_tournament_positions AS position
                WHERE position.portfolio_account_id = account.id
            )
        ),
        ranked AS (
            SELECT
                versions.*,
                ROW_NUMBER() OVER (
                    PARTITION BY old_account_id
                    ORDER BY first_observed_at, execution_config_version
                ) AS version_number
            FROM (
                SELECT * FROM positioned
                UNION ALL
                SELECT * FROM unpositioned
            ) AS versions
        )
        SELECT
            old_account_id,
            execution_config_version,
            version_number,
            CASE
                WHEN version_number = 1 THEN old_account_id
                ELSE gen_random_uuid()
            END AS new_account_id
        FROM ranked
        """
    )

    op.execute(
        """
        UPDATE ai_tournament_portfolios AS account
        SET execution_config_version = target.execution_config_version
        FROM _portfolio_execution_targets AS target
        WHERE
            target.old_account_id = account.id
            AND target.version_number = 1
        """
    )
    op.execute(
        """
        INSERT INTO ai_tournament_portfolios (
            id,
            canonical_event_id,
            provider,
            model,
            prompt_version,
            decision_policy_version,
            ai_view_version,
            execution_config_version,
            initial_bankroll,
            cash_balance,
            locked_balance,
            realized_pnl,
            peak_equity,
            max_drawdown,
            max_drawdown_pct,
            status,
            created_at,
            updated_at
        )
        SELECT
            target.new_account_id,
            original.canonical_event_id,
            original.provider,
            original.model,
            original.prompt_version,
            original.decision_policy_version,
            original.ai_view_version,
            target.execution_config_version,
            original.initial_bankroll,
            original.initial_bankroll,
            0,
            0,
            original.initial_bankroll,
            0,
            0,
            'ACTIVE',
            original.created_at,
            original.updated_at
        FROM _portfolio_execution_targets AS target
        JOIN ai_tournament_portfolios AS original
            ON original.id = target.old_account_id
        WHERE target.version_number > 1
        """
    )
    op.execute(
        """
        UPDATE ai_tournament_positions AS position
        SET portfolio_account_id = target.new_account_id
        FROM ai_decisions AS decision, _portfolio_execution_targets AS target
        WHERE
            decision.id = position.ai_decision_id
            AND target.old_account_id = position.portfolio_account_id
            AND target.execution_config_version = decision.execution_config_version
        """
    )
    op.execute(
        """
        UPDATE ai_tournament_ledger AS ledger
        SET portfolio_account_id = position.portfolio_account_id
        FROM ai_tournament_positions AS position
        WHERE ledger.position_id = position.id
        """
    )
    op.execute(
        """
        INSERT INTO ai_tournament_ledger (
            id,
            portfolio_account_id,
            position_id,
            entry_type,
            cash_delta,
            locked_delta,
            realized_pnl_delta,
            cash_after,
            locked_after,
            equity_after,
            dedupe_key,
            occurred_at
        )
        SELECT
            gen_random_uuid(),
            target.new_account_id,
            NULL,
            'EVENT_FUNDED',
            original.initial_bankroll,
            0,
            0,
            original.initial_bankroll,
            0,
            original.initial_bankroll,
            'fund:' || target.new_account_id::text,
            COALESCE(
                (
                    SELECT MIN(ledger.occurred_at)
                    FROM ai_tournament_ledger AS ledger
                    WHERE
                        ledger.portfolio_account_id = target.old_account_id
                        AND ledger.entry_type = 'EVENT_FUNDED'
                ),
                original.created_at
            )
        FROM _portfolio_execution_targets AS target
        JOIN ai_tournament_portfolios AS original
            ON original.id = target.old_account_id
        WHERE NOT EXISTS (
            SELECT 1
            FROM ai_tournament_ledger AS funded
            WHERE
                funded.portfolio_account_id = target.new_account_id
                AND funded.entry_type = 'EVENT_FUNDED'
        )
        """
    )
    _recompute_portfolios()

    op.alter_column(
        "ai_tournament_portfolios",
        "execution_config_version",
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_ai_tournament_portfolio_experiment",
        "ai_tournament_portfolios",
        [
            "canonical_event_id",
            "provider",
            "model",
            "prompt_version",
            "decision_policy_version",
            "ai_view_version",
            "execution_config_version",
        ],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_ai_tournament_portfolio_experiment",
        "ai_tournament_portfolios",
        type_="unique",
    )
    op.execute(
        """
        CREATE TEMPORARY TABLE _portfolio_merge_targets ON COMMIT DROP AS
        SELECT
            id AS account_id,
            FIRST_VALUE(id) OVER (
                PARTITION BY
                    canonical_event_id,
                    provider,
                    model,
                    prompt_version,
                    decision_policy_version,
                    ai_view_version
                ORDER BY created_at, id
            ) AS primary_account_id
        FROM ai_tournament_portfolios
        """
    )
    op.execute(
        """
        UPDATE ai_tournament_positions AS position
        SET portfolio_account_id = target.primary_account_id
        FROM _portfolio_merge_targets AS target
        WHERE target.account_id = position.portfolio_account_id
        """
    )
    op.execute(
        """
        UPDATE ai_tournament_ledger AS ledger
        SET portfolio_account_id = position.portfolio_account_id
        FROM ai_tournament_positions AS position
        WHERE ledger.position_id = position.id
        """
    )
    op.execute(
        """
        DELETE FROM ai_tournament_ledger AS ledger
        USING _portfolio_merge_targets AS target
        WHERE
            ledger.portfolio_account_id = target.account_id
            AND target.account_id <> target.primary_account_id
            AND ledger.position_id IS NULL
        """
    )
    op.execute(
        """
        DELETE FROM ai_tournament_portfolios AS account
        USING _portfolio_merge_targets AS target
        WHERE
            account.id = target.account_id
            AND target.account_id <> target.primary_account_id
        """
    )
    _recompute_portfolios()
    op.drop_column("ai_tournament_portfolios", "execution_config_version")
    op.create_unique_constraint(
        "uq_ai_tournament_portfolio_experiment",
        "ai_tournament_portfolios",
        [
            "canonical_event_id",
            "provider",
            "model",
            "prompt_version",
            "decision_policy_version",
            "ai_view_version",
        ],
    )

    op.drop_constraint("uq_ai_experiment", "ai_decisions", type_="unique")
    op.drop_column("ai_decisions", "execution_config_version")
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
