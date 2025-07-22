"""add unique constraint to command_invocations

Revision ID: 0d9af2321b54
Revises: 32bff6a875bd
Create Date: 2025-07-22 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '0d9af2321b54'
down_revision: Union[str, None] = '32bff6a875bd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        'uniq_cmd_inv_guild_chan_user_cmd_ts',
        'command_invocations',
        ['guild_id', 'channel_id', 'user_id', 'command', 'created_at'],
        schema='discord',
    )


def downgrade() -> None:
    op.drop_constraint(
        'uniq_cmd_inv_guild_chan_user_cmd_ts',
        'command_invocations',
        schema='discord',
    )
