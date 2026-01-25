"""Add announced_milestones column to user_streak table.

This column tracks which streak milestones have been publicly announced
using a bitmask:
- bit 0 (value 1): 7-day milestone announced
- bit 1 (value 2): 14-day milestone announced
- bit 2 (value 4): 30-day milestone announced
- bit 3 (value 8): 60-day milestone announced
- bit 4 (value 16): 100-day milestone announced

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-01-25 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user_streak",
        sa.Column(
            "announced_milestones",
            sa.Integer,
            nullable=False,
            server_default="0",
        ),
        schema="discord",
    )


def downgrade() -> None:
    op.drop_column("user_streak", "announced_milestones", schema="discord")
