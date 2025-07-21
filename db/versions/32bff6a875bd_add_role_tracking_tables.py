"""add role tracking tables

Revision ID: 32bff6a875bd
Revises: 92ffba02de5d
Create Date: 2025-08-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '32bff6a875bd'
down_revision: Union[str, None] = '92ffba02de5d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'guild_role',
        sa.Column('role_id', sa.BigInteger, primary_key=True),
        sa.Column('guild_id', sa.BigInteger, sa.ForeignKey('guild.guild_id', ondelete='CASCADE')),
        sa.Column('name', sa.Text, nullable=False),
        sa.Column('color_rgb', sa.Integer),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        schema='discord',
    )
    op.create_table(
        'role_assignment',
        sa.Column('guild_id', sa.BigInteger, nullable=False),
        sa.Column('role_id', sa.BigInteger, nullable=False),
        sa.Column('user_id', sa.BigInteger, nullable=False),
        sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('guild_id', 'role_id', 'user_id'),
        schema='discord',
    )
    op.create_table(
        'role_event',
        sa.Column('event_id', sa.BigInteger, primary_key=True),
        sa.Column('guild_id', sa.BigInteger, nullable=False),
        sa.Column('role_id', sa.BigInteger, nullable=False),
        sa.Column('user_id', sa.BigInteger, nullable=False),
        sa.Column('action', sa.SmallInteger, nullable=False),
        sa.Column('event_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        schema='discord',
    )
    op.create_index('role_event_ts', 'role_event', ['event_at'], schema='discord')
    op.create_index('role_event_user', 'role_event', ['user_id', 'event_at'], schema='discord')


def downgrade() -> None:
    op.drop_index('role_event_user', table_name='role_event', schema='discord')
    op.drop_index('role_event_ts', table_name='role_event', schema='discord')
    op.drop_table('role_event', schema='discord')
    op.drop_table('role_assignment', schema='discord')
    op.drop_table('guild_role', schema='discord')
