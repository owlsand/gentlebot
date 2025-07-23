"""rename guild_role table to role and store full Role data"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'ed53baa71962'
down_revision: Union[str, None] = '5db745141237'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table('guild_role', 'role', schema='discord')
    op.add_column('role', sa.Column('permissions', sa.BigInteger), schema='discord')
    op.add_column('role', sa.Column('position', sa.Integer), schema='discord')
    op.add_column('role', sa.Column('hoist', sa.Boolean, server_default=sa.text('false')), schema='discord')
    op.add_column('role', sa.Column('mentionable', sa.Boolean, server_default=sa.text('false')), schema='discord')
    op.add_column('role', sa.Column('managed', sa.Boolean, server_default=sa.text('false')), schema='discord')
    op.add_column('role', sa.Column('icon_hash', sa.Text), schema='discord')
    op.add_column('role', sa.Column('unicode_emoji', sa.Text), schema='discord')
    op.add_column('role', sa.Column('flags', sa.Integer), schema='discord')
    op.add_column('role', sa.Column('tags', sa.JSON, server_default='{}'), schema='discord')


def downgrade() -> None:
    op.drop_column('role', 'tags', schema='discord')
    op.drop_column('role', 'flags', schema='discord')
    op.drop_column('role', 'unicode_emoji', schema='discord')
    op.drop_column('role', 'icon_hash', schema='discord')
    op.drop_column('role', 'managed', schema='discord')
    op.drop_column('role', 'mentionable', schema='discord')
    op.drop_column('role', 'hoist', schema='discord')
    op.drop_column('role', 'position', schema='discord')
    op.drop_column('role', 'permissions', schema='discord')
    op.rename_table('role', 'guild_role', schema='discord')
