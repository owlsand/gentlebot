"""create daily_prompt table"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '13a7e7c7add3'
down_revision: Union[str, None] = 'f72b0b402bbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        'daily_prompt',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
        ),
        sa.Column('prompt', sa.Text, nullable=False, unique=True),
        sa.Column('category', sa.Text, nullable=False),
        sa.Column('thread_channel_id', sa.BigInteger, nullable=False),
        sa.Column('message_count', sa.Integer, nullable=False, server_default='0'),
        schema='discord',
    )


def downgrade() -> None:
    op.drop_table('daily_prompt', schema='discord')
