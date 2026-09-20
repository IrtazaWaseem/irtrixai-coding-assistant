"""add_provider_and_model_to_tasks

Revision ID: 314f2c259334
Revises: 0001_initial_schema
Create Date: 2026-09-20 21:15:11.950639

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "314f2c259334"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("provider", sa.String(length=64), nullable=True))
    op.add_column("tasks", sa.Column("model", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "model")
    op.drop_column("tasks", "provider")
