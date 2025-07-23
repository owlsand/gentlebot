"""add flags column to message table

Revision ID: 25c9a6b568d1
Revises: 0d9af2321b54
Create Date: 2025-09-01 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '25c9a6b568d1'
down_revision: Union[str, None] = '0d9af2321b54'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'message',
        sa.Column('flags', sa.Integer, server_default='0', nullable=False),
        schema='discord'
    )


def downgrade() -> None:
    op.drop_column('message', 'flags', schema='discord')

