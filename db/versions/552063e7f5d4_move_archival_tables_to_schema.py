"""move message archival tables to discord schema

Revision ID: 552063e7f5d4
Revises: bcc44b374343
Create Date: 2025-08-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '552063e7f5d4'
down_revision: Union[str, None] = 'bcc44b374343'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS discord")
    for table in (
        "channel",
        "guild",
        "message",
        "message_attachment",
        "reaction_event",
        "user",
    ):
        op.execute(f"ALTER TABLE {table} SET SCHEMA discord")


def downgrade() -> None:
    for table in (
        "channel",
        "guild",
        "message",
        "message_attachment",
        "reaction_event",
        "user",
    ):
        op.execute(f"ALTER TABLE discord.{table} SET SCHEMA public")
    op.execute("DROP SCHEMA IF EXISTS discord")
