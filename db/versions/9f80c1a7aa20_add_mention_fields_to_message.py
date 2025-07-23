"""add mention fields to message table

Revision ID: 9f80c1a7aa20
Revises: 25c9a6b568d1
Create Date: 2025-09-02 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '9f80c1a7aa20'
down_revision: Union[str, None] = '25c9a6b568d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'message',
        sa.Column('mention_everyone', sa.Boolean, server_default='false', nullable=False),
        schema='discord'
    )
    op.add_column(
        'message',
        sa.Column('mentions', sa.JSON, server_default='[]', nullable=False),
        schema='discord'
    )
    op.add_column(
        'message',
        sa.Column('mention_roles', sa.JSON, server_default='[]', nullable=False),
        schema='discord'
    )
    op.add_column(
        'message',
        sa.Column('embeds', sa.JSON, server_default='[]', nullable=False),
        schema='discord'
    )


def downgrade() -> None:
    op.drop_column('message', 'embeds', schema='discord')
    op.drop_column('message', 'mention_roles', schema='discord')
    op.drop_column('message', 'mentions', schema='discord')
    op.drop_column('message', 'mention_everyone', schema='discord')
