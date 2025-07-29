"""add unique constraint to reaction_event"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '0621c7d3e3d7'
down_revision: Union[str, None] = 'f72b0b402bbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM discord.reaction_event
        WHERE event_id IN (
            SELECT event_id FROM (
                SELECT event_id,
                    row_number() OVER (
                        PARTITION BY message_id, user_id, emoji, action, event_at
                        ORDER BY event_id
                    ) AS rn
                FROM discord.reaction_event
            ) dup
            WHERE dup.rn > 1
        )
        """
    )
    op.create_unique_constraint(
        'uniq_reaction_event_msg_user_emoji_act_ts',
        'reaction_event',
        ['message_id', 'user_id', 'emoji', 'action', 'event_at'],
        schema='discord',
    )


def downgrade() -> None:
    op.drop_constraint(
        'uniq_reaction_event_msg_user_emoji_act_ts',
        'reaction_event',
        schema='discord',
    )
