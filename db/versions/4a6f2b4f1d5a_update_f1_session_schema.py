"""update f1_session schema

Revision ID: 4a6f2b4f1d5a
Revises: f288b9a2c9d3
Create Date: 2025-10-02 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '4a6f2b4f1d5a'
down_revision: Union[str, None] = 'f288b9a2c9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('idx_f1_start_time', table_name='f1_session', schema='discord')
    op.drop_table('f1_session', schema='discord')
    op.create_table(
        'f1_session',
        sa.Column('id', sa.BigInteger, primary_key=True),
        sa.Column('country_iso', sa.String(2), nullable=False),
        sa.Column('year', sa.Integer, nullable=False),
        sa.Column('gp_name', sa.Text, nullable=False),
        sa.Column('session', sa.Text, nullable=False),
        sa.Column('starts_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('thread_id', sa.BigInteger),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('year', 'gp_name', 'session', name='uniq_f1_year_gp_session'),
        schema='discord',
    )
    op.create_index('idx_f1_starts_at', 'f1_session', ['starts_at'], schema='discord')


def downgrade() -> None:
    op.drop_index('idx_f1_starts_at', table_name='f1_session', schema='discord')
    op.drop_table('f1_session', schema='discord')
    op.create_table(
        'f1_session',
        sa.Column('session_id', sa.BigInteger, primary_key=True),
        sa.Column('round', sa.Text, nullable=False),
        sa.Column('session', sa.Text, nullable=False),
        sa.Column('slug', sa.Text, nullable=False),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('thread_id', sa.BigInteger),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.UniqueConstraint('round', 'session', name='uniq_f1_round_session'),
        schema='discord',
    )
    op.create_index('idx_f1_start_time', 'f1_session', ['start_time'], schema='discord')
