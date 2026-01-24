"""Create task execution tracking table.

This table tracks scheduled task executions to support idempotency,
preventing duplicate task runs after bot restarts or crashes.

Revision ID: fb67328ce99c
Revises: b1e4d1ffebd6
Create Date: 2026-01-23 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "fb67328ce99c"
down_revision: Union[str, None] = "b1e4d1ffebd6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_execution",
        sa.Column("task_name", sa.Text, nullable=False),
        sa.Column("execution_key", sa.Text, nullable=False),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("result", sa.Text, nullable=True),
        sa.PrimaryKeyConstraint("task_name", "execution_key"),
        schema="discord",
    )
    op.create_index(
        "ix_task_execution_task_executed",
        "task_execution",
        ["task_name", "executed_at"],
        schema="discord",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_task_execution_task_executed",
        table_name="task_execution",
        schema="discord",
    )
    op.drop_table("task_execution", schema="discord")
