"""add command_invocations table

Revision ID: 92ffba02de5d
Revises: 415493c2f0a9
Create Date: 2025-08-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '92ffba02de5d'
down_revision: Union[str, None] = '415493c2f0a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'command_invocations',
        sa.Column('id', sa.BigInteger, primary_key=True),
        sa.Column('guild_id', sa.BigInteger, nullable=False),
        sa.Column('channel_id', sa.BigInteger, nullable=False),
        sa.Column('user_id', sa.BigInteger, nullable=False),
        sa.Column('command', sa.Text, nullable=False),
        sa.Column(
            'args_json',
            sa.JSON,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        schema='discord',
    )
    op.create_index(
        'idx_command_inv_created_at',
        'command_invocations',
        ['created_at'],
        schema='discord',
    )
    op.create_index(
        'idx_command_inv_cmd',
        'command_invocations',
        ['command'],
        schema='discord',
    )


def downgrade() -> None:
    op.drop_index(
        'idx_command_inv_cmd',
        table_name='command_invocations',
        schema='discord',
    )
    op.drop_index(
        'idx_command_inv_created_at',
        table_name='command_invocations',
        schema='discord',
    )
    op.drop_table('command_invocations', schema='discord')

