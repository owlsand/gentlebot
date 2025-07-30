"""merge heads

Revision ID: 0f0d227664a7
Revises: 3b4d7c9da68e, 5da39b923f95
Create Date: 2025-07-30 23:23:48.415284

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0f0d227664a7'
down_revision: Union[str, None] = ('3b4d7c9da68e', '5da39b923f95')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
