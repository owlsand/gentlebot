"""merge heads

Revision ID: a19f6ae0c2d3
Revises: f288b9a2c9d3, f72b0b402bbc
Create Date: 2025-10-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a19f6ae0c2d3'
down_revision: Union[str, None] = ('f288b9a2c9d3', 'f72b0b402bbc')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
