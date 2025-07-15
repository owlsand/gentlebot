"""create bot_logs table

Revision ID: 1e7784a88d64
Revises: 
Create Date: 2025-07-14 04:03:58.620771

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1e7784a88d64'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bot_logs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("logger_name", sa.Text, nullable=False),
        sa.Column("log_level", sa.Text, nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("bot_logs")
