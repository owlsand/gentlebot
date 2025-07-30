"""add message_type reference table

Revision ID: 3b4d7c9da68e
Revises: a19f6ae0c2d3
Create Date: 2025-10-03 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '3b4d7c9da68e'
down_revision: Union[str, None] = 'a19f6ae0c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MESSAGE_TYPES = [
    (0, 'default'),
    (1, 'recipient_add'),
    (2, 'recipient_remove'),
    (3, 'call'),
    (4, 'channel_name_change'),
    (5, 'channel_icon_change'),
    (6, 'pins_add'),
    (7, 'new_member'),
    (8, 'premium_guild_subscription'),
    (9, 'premium_guild_tier_1'),
    (10, 'premium_guild_tier_2'),
    (11, 'premium_guild_tier_3'),
    (12, 'channel_follow_add'),
    (13, 'guild_stream'),
    (14, 'guild_discovery_disqualified'),
    (15, 'guild_discovery_requalified'),
    (16, 'guild_discovery_grace_period_initial_warning'),
    (17, 'guild_discovery_grace_period_final_warning'),
    (18, 'thread_created'),
    (19, 'reply'),
    (20, 'chat_input_command'),
    (21, 'thread_starter_message'),
    (22, 'guild_invite_reminder'),
    (23, 'context_menu_command'),
    (24, 'auto_moderation_action'),
    (25, 'role_subscription_purchase'),
    (26, 'interaction_premium_upsell'),
    (27, 'stage_start'),
    (28, 'stage_end'),
    (29, 'stage_speaker'),
    (30, 'stage_raise_hand'),
    (31, 'stage_topic'),
    (32, 'guild_application_premium_subscription'),
    (36, 'guild_incident_alert_mode_enabled'),
    (37, 'guild_incident_alert_mode_disabled'),
    (38, 'guild_incident_report_raid'),
    (39, 'guild_incident_report_false_alarm'),
    (44, 'purchase_notification'),
    (46, 'poll_result'),
]


def upgrade() -> None:
    op.create_table(
        'message_type',
        sa.Column('type', sa.SmallInteger, primary_key=True),
        sa.Column('name', sa.Text, nullable=False, unique=True),
        schema='discord',
    )
    op.bulk_insert(
        sa.table(
            'message_type',
            sa.column('type', sa.SmallInteger),
            sa.column('name', sa.Text),
        ),
        [{'type': t, 'name': n} for t, n in MESSAGE_TYPES],
    )


def downgrade() -> None:
    op.drop_table('message_type', schema='discord')
