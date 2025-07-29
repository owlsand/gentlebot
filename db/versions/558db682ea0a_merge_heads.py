"""merge heads

Revision ID: 558db682ea0a
Revises: 4c66285ed784, 0621c7d3e3d7
Create Date: 2025-07-29 03:49:28.416505

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '558db682ea0a'
down_revision: Union[str, None] = ('4c66285ed784', '0621c7d3e3d7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
