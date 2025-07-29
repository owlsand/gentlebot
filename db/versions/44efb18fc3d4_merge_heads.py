"""merge heads

Revision ID: 44efb18fc3d4
Revises: 0621c7d3e3d7, 4c66285ed784, d30dcdd2cd68
Create Date: 2025-08-31 00:00:01.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '44efb18fc3d4'
down_revision: Union[str, None] = (
    '0621c7d3e3d7',
    '4c66285ed784',
    'd30dcdd2cd68',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
