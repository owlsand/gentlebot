"""add channel privacy columns

Revision ID: 4b58c5e66f5d
Revises: d24e408ee6dc
Create Date: 2025-09-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '4b58c5e66f5d'
down_revision: Union[str, None] = 'd24e408ee6dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    privacy = sa.Enum(
        'public',
        'guild_restricted',
        'dm',
        'group_dm',
        'private_thread',
        name='channelprivacykind',
    )
    privacy.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'channel',
        sa.Column('privacy_kind', privacy, server_default='public', nullable=False),
        schema='discord',
    )
    op.add_column(
        'channel',
        sa.Column(
            'is_private',
            sa.Boolean,
            sa.Computed("privacy_kind <> 'public'", persisted=True),
            nullable=False,
        ),
        schema='discord',
    )


def downgrade() -> None:
    op.drop_column('channel', 'is_private', schema='discord')
    op.drop_column('channel', 'privacy_kind', schema='discord')
    sa.Enum(name='channelprivacykind').drop(op.get_bind(), checkfirst=True)
