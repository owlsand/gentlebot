"""rename action column to reaction_action enum

Revision ID: d30dcdd2cd68
Revises: f72b0b402bbc
Create Date: 2025-08-31 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'd30dcdd2cd68'
down_revision: Union[str, None] = 'f72b0b402bbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE TYPE reaction_action AS ENUM ('MESSAGE_REACTION_ADD', 'MESSAGE_REACTION_REMOVE')")
    op.add_column(
        'reaction_event',
        sa.Column('reaction_action', sa.Enum('MESSAGE_REACTION_ADD', 'MESSAGE_REACTION_REMOVE', name='reaction_action'), nullable=True),
        schema='discord',
    )
    op.execute(
        "UPDATE discord.reaction_event SET reaction_action = CASE "
        "WHEN action = 0 THEN 'MESSAGE_REACTION_ADD' "
        "ELSE 'MESSAGE_REACTION_REMOVE' END"
    )
    op.alter_column('reaction_event', 'reaction_action', nullable=False, schema='discord')
    op.drop_constraint('uniq_reaction_event_msg_user_emoji_act_ts', 'reaction_event', schema='discord')
    op.create_unique_constraint(
        'uniq_reaction_event_msg_user_emoji_act_ts',
        'reaction_event',
        ['message_id', 'user_id', 'emoji', 'reaction_action', 'event_at'],
        schema='discord',
    )
    op.drop_column('reaction_event', 'action', schema='discord')


def downgrade() -> None:
    op.add_column('reaction_event', sa.Column('action', sa.SmallInteger, nullable=False), schema='discord')
    op.execute(
        "UPDATE discord.reaction_event SET action = CASE "
        "WHEN reaction_action = 'MESSAGE_REACTION_ADD' THEN 0 "
        "ELSE 1 END"
    )
    op.drop_constraint('uniq_reaction_event_msg_user_emoji_act_ts', 'reaction_event', schema='discord')
    op.create_unique_constraint(
        'uniq_reaction_event_msg_user_emoji_act_ts',
        'reaction_event',
        ['message_id', 'user_id', 'emoji', 'action', 'event_at'],
        schema='discord',
    )
    op.drop_column('reaction_event', 'reaction_action', schema='discord')
    op.execute('DROP TYPE reaction_action')
