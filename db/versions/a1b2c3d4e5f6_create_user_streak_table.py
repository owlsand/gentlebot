"""Create user_streak table for engagement tracking.

This table tracks consecutive daily engagement streaks for each user,
enabling milestone role rewards based on streak length.

Revision ID: a1b2c3d4e5f6
Revises: fb67328ce99c
Create Date: 2026-01-24 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "fb67328ce99c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_streak",
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("current_streak", sa.Integer, nullable=False, server_default="0"),
        sa.Column("longest_streak", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_active_date", sa.Date, nullable=False),
        sa.Column("streak_started_date", sa.Date, nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("user_id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["discord.user.user_id"],
            name="fk_user_streak_user_id",
        ),
        schema="discord",
    )
    op.create_index(
        "ix_user_streak_current",
        "user_streak",
        ["current_streak"],
        schema="discord",
        postgresql_using="btree",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_streak_current",
        table_name="user_streak",
        schema="discord",
    )
    op.drop_table("user_streak", schema="discord")
