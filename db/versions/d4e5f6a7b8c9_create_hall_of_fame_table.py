"""Create hall_of_fame table for community-curated message archive.

This table tracks messages that receive high engagement and get nominated
for the Hall of Fame. Community members vote on nominated messages, and
those reaching the vote threshold are inducted (cross-posted to #hall-of-fame).

Lifecycle:
1. Message receives 10+ reactions -> nominated (entry created, inducted_at=NULL)
2. Community taps trophy emoji to vote -> vote_count increments
3. vote_count >= 3 -> inducted (inducted_at set, hof_message_id set)

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-02-02 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hall_of_fame",
        sa.Column("entry_id", sa.Integer, primary_key=True),
        sa.Column("message_id", sa.BigInteger, nullable=False, unique=True),
        sa.Column("channel_id", sa.BigInteger, nullable=False),
        sa.Column("author_id", sa.BigInteger, nullable=False),
        sa.Column(
            "nominated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "inducted_at",
            sa.DateTime(timezone=True),
            nullable=True,  # NULL until votes reach threshold
        ),
        sa.Column("vote_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "hof_message_id",
            sa.BigInteger,
            nullable=True,  # ID of cross-posted message in #hall-of-fame
        ),
        schema="discord",
    )

    # Index for finding non-inducted nominations (for voting)
    op.create_index(
        "ix_hall_of_fame_pending",
        "hall_of_fame",
        ["inducted_at"],
        schema="discord",
        postgresql_where=sa.text("inducted_at IS NULL"),
    )

    # Index for author statistics
    op.create_index(
        "ix_hall_of_fame_author",
        "hall_of_fame",
        ["author_id"],
        schema="discord",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hall_of_fame_author",
        table_name="hall_of_fame",
        schema="discord",
    )
    op.drop_index(
        "ix_hall_of_fame_pending",
        table_name="hall_of_fame",
        schema="discord",
    )
    op.drop_table("hall_of_fame", schema="discord")
