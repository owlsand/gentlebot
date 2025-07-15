"""add display_name column to user table

Revision ID: 415493c2f0a9
Revises: 552063e7f5d4
Create Date: 2025-07-15 03:22:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '415493c2f0a9'
down_revision: Union[str, None] = '552063e7f5d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'user',
        sa.Column('display_name', sa.Text),
        schema='discord'
    )
    op.execute('UPDATE discord."user" SET display_name = username')


def downgrade() -> None:
    op.drop_column('user', 'display_name', schema='discord')
