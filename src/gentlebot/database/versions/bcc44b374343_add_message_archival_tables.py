"""add message archival tables

Revision ID: bcc44b374343
Revises: 1e7784a88d64
Create Date: 2025-07-14 17:57:55.235165

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'bcc44b374343'
down_revision: Union[str, None] = '1e7784a88d64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "guild",
        sa.Column("guild_id", sa.BigInteger, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("owner_id", sa.BigInteger),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "user",
        sa.Column("user_id", sa.BigInteger, primary_key=True),
        sa.Column("username", sa.Text, nullable=False),
        sa.Column("discriminator", sa.Text),
        sa.Column("avatar_hash", sa.Text),
        sa.Column("is_bot", sa.Boolean, server_default=sa.text("false")),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "channel",
        sa.Column("channel_id", sa.BigInteger, primary_key=True),
        sa.Column(
            "guild_id",
            sa.BigInteger,
            sa.ForeignKey("guild.guild_id", ondelete="CASCADE"),
        ),
        sa.Column("name", sa.Text),
        sa.Column("type", sa.SmallInteger, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "message",
        sa.Column("message_id", sa.BigInteger, primary_key=True),
        sa.Column(
            "guild_id",
            sa.BigInteger,
            sa.ForeignKey("guild.guild_id", ondelete="CASCADE"),
        ),
        sa.Column(
            "channel_id",
            sa.BigInteger,
            sa.ForeignKey("channel.channel_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.BigInteger,
            sa.ForeignKey("user.user_id"),
            nullable=False,
        ),
        sa.Column(
            "reply_to_id",
            sa.BigInteger,
            sa.ForeignKey("message.message_id", deferrable=True, initially="DEFERRED"),
        ),
        sa.Column("content", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True)),
        sa.Column("pinned", sa.Boolean, server_default=sa.text("false")),
        sa.Column("tts", sa.Boolean, server_default=sa.text("false")),
        sa.Column("type", sa.SmallInteger, nullable=False),
        sa.Column("raw_payload", sa.JSON, nullable=False),
    )
    op.create_index("msg_channel_ts", "message", ["channel_id", "created_at"])
    op.create_index("msg_author_ts", "message", ["author_id", "created_at"])
    op.create_table(
        "message_attachment",
        sa.Column(
            "message_id",
            sa.BigInteger,
            sa.ForeignKey("message.message_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attachment_id", sa.Integer, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("content_type", sa.Text),
        sa.Column("size_bytes", sa.Integer),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("proxy_url", sa.Text),
        sa.PrimaryKeyConstraint("message_id", "attachment_id"),
    )
    op.create_table(
        "reaction_event",
        sa.Column("event_id", sa.BigInteger, primary_key=True),
        sa.Column(
            "message_id",
            sa.BigInteger,
            sa.ForeignKey("message.message_id", ondelete="CASCADE"),
        ),
        sa.Column("user_id", sa.BigInteger, sa.ForeignKey("user.user_id")),
        sa.Column("emoji", sa.Text, nullable=False),
        sa.Column("action", sa.SmallInteger, nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("reaction_event")
    op.drop_table("message_attachment")
    op.drop_index("msg_author_ts", table_name="message")
    op.drop_index("msg_channel_ts", table_name="message")
    op.drop_table("message")
    op.drop_table("channel")
    op.drop_table("user")
    op.drop_table("guild")
