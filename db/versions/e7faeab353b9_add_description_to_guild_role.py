"""add description column to guild_role

Revision ID: e7faeab353b9
Revises: 0d9af2321b54
Create Date: 2025-08-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e7faeab353b9'
down_revision: Union[str, None] = '0d9af2321b54'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'guild_role',
        sa.Column('description', sa.Text),
        schema='discord',
    )


def downgrade() -> None:
    op.drop_column('guild_role', 'description', schema='discord')
