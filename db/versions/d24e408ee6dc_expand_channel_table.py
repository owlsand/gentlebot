"""expand discord.channel table

Revision ID: d24e408ee6dc
Revises: e7faeab353b9
Create Date: 2025-09-01 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd24e408ee6dc'
down_revision: Union[str, None] = 'e7faeab353b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('channel', sa.Column('position', sa.Integer), schema='discord')
    op.add_column('channel', sa.Column('parent_id', sa.BigInteger), schema='discord')
    op.add_column('channel', sa.Column('topic', sa.Text), schema='discord')
    op.add_column('channel', sa.Column('nsfw', sa.Boolean), schema='discord')
    op.add_column('channel', sa.Column('last_message_id', sa.BigInteger), schema='discord')
    op.add_column('channel', sa.Column('rate_limit_per_user', sa.Integer), schema='discord')
    op.add_column('channel', sa.Column('bitrate', sa.Integer), schema='discord')
    op.add_column('channel', sa.Column('user_limit', sa.Integer), schema='discord')


def downgrade() -> None:
    op.drop_column('channel', 'last_message_id', schema='discord')
    op.drop_column('channel', 'nsfw', schema='discord')
    op.drop_column('channel', 'topic', schema='discord')
    op.drop_column('channel', 'parent_id', schema='discord')
    op.drop_column('channel', 'position', schema='discord')
    op.drop_column('channel', 'user_limit', schema='discord')
    op.drop_column('channel', 'bitrate', schema='discord')
    op.drop_column('channel', 'rate_limit_per_user', schema='discord')
