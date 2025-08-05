"""create presence_update table"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '21f8d03f7509'
down_revision: Union[str, None] = '0621c7d3e3d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    op.create_table(
        'presence_update',
        sa.Column('event_id', sa.BigInteger, primary_key=True),
        sa.Column('guild_id', sa.BigInteger, nullable=False),
        sa.Column('user_id', sa.BigInteger, nullable=False),
        sa.Column('status', sa.Text, nullable=False),
        sa.Column('activities', sa.JSON),
        sa.Column('client_status', sa.JSON),
        sa.Column(
            'event_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        schema='discord',
    )
    op.create_index(
        'presence_update_guild_user',
        'presence_update',
        ['guild_id', 'user_id', 'event_at'],
        schema='discord',
    )


def downgrade() -> None:
    op.drop_index('presence_update_guild_user', table_name='presence_update', schema='discord')
    op.drop_table('presence_update', schema='discord')
