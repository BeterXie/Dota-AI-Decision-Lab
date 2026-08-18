"""Normalize the competition pass purchase check constraint name.

Revision ID: 0040_normalize_competition_pass_purchase_constraint
Revises: 0039_competition_passes_and_stage_access
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0040_normalize_competition_pass_purchase_constraint"
down_revision: str | None = "0039_competition_passes_and_stage_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_NAME = "ck_competition_pass_purchases_ck_competition_pass_purch_bdac"
_NEW_NAME = "ck_competition_pass_purchases_pass_scope"


def upgrade() -> None:
    statement = (
        f'ALTER TABLE competition_pass_purchases RENAME CONSTRAINT "{_OLD_NAME}" TO "{_NEW_NAME}"'
    )
    op.execute(sa.text(statement))


def downgrade() -> None:
    statement = (
        f'ALTER TABLE competition_pass_purchases RENAME CONSTRAINT "{_NEW_NAME}" TO "{_OLD_NAME}"'
    )
    op.execute(sa.text(statement))
