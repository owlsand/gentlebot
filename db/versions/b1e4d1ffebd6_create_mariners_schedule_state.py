"""Create Mariners schedule state table.

Revision ID: b1e4d1ffebd6
Revises: f493dfd9bc5b
Create Date: 2025-03-06 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b1e4d1ffebd6"
down_revision: Union[str, None] = "f493dfd9bc5b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "mariners_schedule_state",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column(
            "tracking_since",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="discord",
    )
    op.execute(
        """
        INSERT INTO discord.mariners_schedule_state (id, tracking_since)
        VALUES (1, now())
        ON CONFLICT (id) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_table("mariners_schedule_state", schema="discord")
