"""Create user_recap_pref table for monthly recap opt-in preferences.

This table tracks user preferences for receiving monthly personalized
recap DMs with engagement statistics.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-01-24 00:00:01.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_recap_pref",
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("opted_in", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("user_id"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["discord.user.user_id"],
            name="fk_user_recap_pref_user_id",
        ),
        schema="discord",
    )


def downgrade() -> None:
    op.drop_table("user_recap_pref", schema="discord")
