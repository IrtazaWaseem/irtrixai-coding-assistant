"""create_initial_schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Create Workspaces Table
    op.create_table(
        "workspaces",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("root_path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workspaces_root_path"), "workspaces", ["root_path"], unique=True
    )

    # 2. Create PostgreSQL ENUM Type Once
    task_status_enum = postgresql.ENUM(
        "PENDING",
        "RUNNING",
        "AWAITING_APPROVAL",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        name="task_status",
    )
    task_status_enum.create(op.get_bind(), checkfirst=True)

    # 3. Create Tasks Table (referencing existing enum)
    op.create_table(
        "tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "PENDING",
                "RUNNING",
                "AWAITING_APPROVAL",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                name="task_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tasks_status"), "tasks", ["status"], unique=False)
    op.create_index(
        op.f("ix_tasks_workspace_id"), "tasks", ["workspace_id"], unique=False
    )

    # 4. Create Runs Table (referencing existing enum)
    op.create_table(
        "runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(
                "PENDING",
                "RUNNING",
                "AWAITING_APPROVAL",
                "COMPLETED",
                "FAILED",
                "CANCELLED",
                name="task_status",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("repair_count", sa.Integer(), nullable=False),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_runs_status"), "runs", ["status"], unique=False)
    op.create_index(op.f("ix_runs_task_id"), "runs", ["task_id"], unique=False)
    op.create_index(op.f("ix_runs_thread_id"), "runs", ["thread_id"], unique=True)

    # 5. Create Agent Events Table
    op.create_table(
        "agent_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("node_name", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_agent_events_created_at"), "agent_events", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_agent_events_event_type"), "agent_events", ["event_type"], unique=False
    )
    op.create_index(
        op.f("ix_agent_events_node_name"), "agent_events", ["node_name"], unique=False
    )
    op.create_index(
        op.f("ix_agent_events_run_id"), "agent_events", ["run_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_events_run_id"), table_name="agent_events")
    op.drop_index(op.f("ix_agent_events_node_name"), table_name="agent_events")
    op.drop_index(op.f("ix_agent_events_event_type"), table_name="agent_events")
    op.drop_index(op.f("ix_agent_events_created_at"), table_name="agent_events")
    op.drop_table("agent_events")

    op.drop_index(op.f("ix_runs_thread_id"), table_name="runs")
    op.drop_index(op.f("ix_runs_task_id"), table_name="runs")
    op.drop_index(op.f("ix_runs_status"), table_name="runs")
    op.drop_table("runs")

    op.drop_index(op.f("ix_tasks_workspace_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_status"), table_name="tasks")
    op.drop_table("tasks")

    task_status_enum = postgresql.ENUM(name="task_status")
    task_status_enum.drop(op.get_bind(), checkfirst=True)

    op.drop_index(op.f("ix_workspaces_root_path"), table_name="workspaces")
    op.drop_table("workspaces")
