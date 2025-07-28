"""add index on role_event role_id,user_id"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'f72b0b402bbc'
down_revision: Union[str, None] = 'ed53baa71962'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'role_event_role_user',
        'role_event',
        ['role_id', 'user_id'],
        unique=False,
        schema='discord',
        postgresql_where=sa.text('action = 1'),
    )


def downgrade() -> None:
    op.drop_index('role_event_role_user', table_name='role_event', schema='discord')
