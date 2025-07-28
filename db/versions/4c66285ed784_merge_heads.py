"""merge heads

Revision ID: 4c66285ed784
Revises: a19f6ae0c2d3, 4a6f2b4f1d5a
Create Date: 2025-07-28 20:49:15.413151

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4c66285ed784'
down_revision: Union[str, None] = ('a19f6ae0c2d3', '4a6f2b4f1d5a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
