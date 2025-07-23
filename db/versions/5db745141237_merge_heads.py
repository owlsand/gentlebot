"""merge heads

Revision ID: 5db745141237
Revises: 9f80c1a7aa20, a8c180046cea, d24e408ee6dc
Create Date: 2025-07-23 03:38:56.141241

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5db745141237'
down_revision: Union[str, None] = ('9f80c1a7aa20', 'a8c180046cea', 'd24e408ee6dc')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
