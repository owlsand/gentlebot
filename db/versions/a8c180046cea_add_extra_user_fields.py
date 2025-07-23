"""add more user fields to match Discord spec

Revision ID: a8c180046cea
Revises: e7faeab353b9
Create Date: 2025-09-01 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a8c180046cea'
down_revision: Union[str, None] = 'e7faeab353b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'user',
        sa.Column('global_name', sa.Text),
        schema='discord'
    )
    op.add_column(
        'user',
        sa.Column('banner_hash', sa.Text),
        schema='discord'
    )
    op.add_column(
        'user',
        sa.Column('accent_color', sa.Integer),
        schema='discord'
    )
    op.add_column(
        'user',
        sa.Column('avatar_decoration_hash', sa.Text),
        schema='discord'
    )
    op.add_column(
        'user',
        sa.Column('system', sa.Boolean, server_default=sa.text('false')),
        schema='discord'
    )
    op.add_column(
        'user',
        sa.Column('public_flags', sa.Integer),
        schema='discord'
    )
    op.execute('UPDATE discord."user" SET global_name = display_name')


def downgrade() -> None:
    op.drop_column('user', 'public_flags', schema='discord')
    op.drop_column('user', 'system', schema='discord')
    op.drop_column('user', 'avatar_decoration_hash', schema='discord')
    op.drop_column('user', 'accent_color', schema='discord')
    op.drop_column('user', 'banner_hash', schema='discord')
    op.drop_column('user', 'global_name', schema='discord')
