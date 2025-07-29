"""merge heads

Revision ID: 53e3f66601f8
Revises: 44efb18fc3d4, 558db682ea0a
Create Date: 2025-07-29 04:22:14.369746

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '53e3f66601f8'
down_revision: Union[str, None] = ('44efb18fc3d4', '558db682ea0a')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
