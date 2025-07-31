"""add channel_type reference table

Revision ID: 24b639ccf447
Revises: 0f0d227664a7
Create Date: 2025-10-04 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '24b639ccf447'
down_revision: Union[str, None] = '0f0d227664a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CHANNEL_TYPES = [
    (0, 'text'),
    (1, 'private'),
    (2, 'voice'),
    (3, 'group'),
    (4, 'category'),
    (5, 'news'),
    (10, 'news_thread'),
    (11, 'public_thread'),
    (12, 'private_thread'),
    (13, 'stage_voice'),
    (15, 'forum'),
    (16, 'media'),
]


def upgrade() -> None:
    op.create_table(
        'channel_type',
        sa.Column('type', sa.SmallInteger, primary_key=True),
        sa.Column('name', sa.Text, nullable=False, unique=True),
        schema='discord',
    )
    op.bulk_insert(
        sa.table(
            'channel_type',
            sa.column('type', sa.SmallInteger),
            sa.column('name', sa.Text),
        ),
        [{'type': t, 'name': n} for t, n in CHANNEL_TYPES],
    )


def downgrade() -> None:
    op.drop_table('channel_type', schema='discord')
