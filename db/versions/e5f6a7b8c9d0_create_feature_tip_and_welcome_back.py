"""Create feature_tip and welcome_back_event tables.

feature_tip: Tracks one-time contextual feature tips sent to users.
Each user sees each tip at most once (PK on user_id + tip_key).

welcome_back_event: Records welcome-back reactions/messages sent when
a lurker or ghost returns after a gap. Indexed on (user_id, sent_at)
for cooldown lookups.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-02-08 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -- feature_tip --
    op.create_table(
        "feature_tip",
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("tip_key", sa.Text, nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("user_id", "tip_key"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["discord.user.user_id"],
            name="fk_feature_tip_user_id",
        ),
        schema="discord",
    )

    # -- welcome_back_event --
    op.create_table(
        "welcome_back_event",
        sa.Column(
            "id",
            sa.Integer,
            primary_key=True,
            autoincrement=True,
        ),
        sa.Column("user_id", sa.BigInteger, nullable=False),
        sa.Column("channel_id", sa.BigInteger, nullable=False),
        sa.Column("gap_days", sa.Integer, nullable=False),
        sa.Column(
            "sent_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["discord.user.user_id"],
            name="fk_welcome_back_event_user_id",
        ),
        schema="discord",
    )

    op.create_index(
        "ix_welcome_back_user",
        "welcome_back_event",
        ["user_id", "sent_at"],
        schema="discord",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_welcome_back_user",
        table_name="welcome_back_event",
        schema="discord",
    )
    op.drop_table("welcome_back_event", schema="discord")
    op.drop_table("feature_tip", schema="discord")
