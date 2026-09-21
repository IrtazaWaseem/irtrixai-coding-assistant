"""add_token_telemetry

Revision ID: 314f2c259335
Revises: 314f2c259334
Create Date: 2026-09-21 12:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "314f2c259335"
down_revision: str | None = "314f2c259334"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Update tasks table
    op.add_column(
        "tasks", sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "tasks", sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "tasks", sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("tasks", sa.Column("llm_calls", sa.Integer(), server_default="0", nullable=False))
    op.add_column(
        "tasks", sa.Column("provider_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )

    # 2. Update runs table
    op.add_column(
        "runs", sa.Column("prompt_tokens", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "runs", sa.Column("completion_tokens", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column(
        "runs", sa.Column("total_tokens", sa.Integer(), server_default="0", nullable=False)
    )
    op.add_column("runs", sa.Column("llm_calls", sa.Integer(), server_default="0", nullable=False))
    op.add_column(
        "runs", sa.Column("provider_usage", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("runs", "provider_usage")
    op.drop_column("runs", "llm_calls")
    op.drop_column("runs", "total_tokens")
    op.drop_column("runs", "completion_tokens")
    op.drop_column("runs", "prompt_tokens")

    op.drop_column("tasks", "provider_usage")
    op.drop_column("tasks", "llm_calls")
    op.drop_column("tasks", "total_tokens")
    op.drop_column("tasks", "completion_tokens")
    op.drop_column("tasks", "prompt_tokens")
