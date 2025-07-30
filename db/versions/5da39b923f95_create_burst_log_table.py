"""create burst log table

Revision ID: 5da39b923f95
Revises: 53e3f66601f8
Create Date: 2025-07-30 04:40:02.555037

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5da39b923f95'
down_revision: Union[str, None] = '53e3f66601f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "burst_log",
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("channel_id", sa.BigInteger, nullable=False),
        sa.Column("thread_id", sa.BigInteger, nullable=False),
        sa.Column("msg_count", sa.Integer, nullable=False),
        sa.Column("author_count", sa.Integer, nullable=False),
        schema="discord",
    )


def downgrade() -> None:
    op.drop_table("burst_log", schema="discord")
