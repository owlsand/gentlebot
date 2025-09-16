"""create mariners schedule table

Revision ID: f493dfd9bc5b
Revises: 5da39b923f95
Create Date: 2025-03-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f493dfd9bc5b'
down_revision: Union[str, None] = '5da39b923f95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mariners_schedule",
        sa.Column("event_id", sa.String(length=32), primary_key=True),
        sa.Column("season_year", sa.Integer, nullable=False),
        sa.Column("game_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("home_away", sa.String(length=4), nullable=False),
        sa.Column("opponent_abbr", sa.String(length=8), nullable=False),
        sa.Column("opponent_name", sa.String(length=128), nullable=False),
        sa.Column("venue", sa.String(length=128), nullable=True),
        sa.Column("short_name", sa.String(length=32), nullable=True),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="pre"),
        sa.Column("mariners_score", sa.Integer, nullable=True),
        sa.Column("opponent_score", sa.Integer, nullable=True),
        sa.Column("summary", sa.JSON, nullable=True),
        sa.Column("message_id", sa.BigInteger, nullable=True),
        sa.Column("message_posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="discord",
    )
    op.create_index(
        "ix_mariners_schedule_season",
        "mariners_schedule",
        ["season_year", "game_date"],
        schema="discord",
    )


def downgrade() -> None:
    op.drop_index("ix_mariners_schedule_season", table_name="mariners_schedule", schema="discord")
    op.drop_table("mariners_schedule", schema="discord")
