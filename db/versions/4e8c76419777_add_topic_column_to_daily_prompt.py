"""add topic column to daily_prompt"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '4e8c76419777'
down_revision: Union[str, None] = '13a7e7c7add3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column(
        'daily_prompt',
        sa.Column('topic', sa.Text, nullable=True),
        schema='discord',
    )

def downgrade() -> None:
    op.drop_column('daily_prompt', 'topic', schema='discord')
