"""Archive Discord messages and reactions to Postgres."""
from __future__ import annotations

import json
import logging
import os
import asyncpg
import discord
from discord.ext import commands
from ..db import get_pool
from ..util import rows_from_tag, ReactionAction

log = logging.getLogger(f"gentlebot.{__name__}")


def _privacy_kind(channel: discord.abc.GuildChannel | discord.abc.PrivateChannel) -> str:
    """Return privacy kind for a Discord channel."""
    ctype = getattr(channel, "type", None)
    value = getattr(ctype, "value", ctype)
    if value == 1:
        return "dm"
    if value == 3:
        return "group_dm"
    if value == 12:
        return "private_thread"
    if value in (10, 11):
        parent = getattr(channel, "parent", None)
        return _privacy_kind(parent) if parent else "public"
    if value in {0, 2, 5, 13, 15, 16, 14}:
        guild = getattr(channel, "guild", None)
        if guild and hasattr(channel, "permissions_for"):
            everyone = getattr(guild, "default_role", None)
            if everyone is not None:
                perms = channel.permissions_for(everyone)
                if getattr(perms, "view_channel", None) is False:
                    return "guild_restricted"
        return "public"
    return "public"


class MessageArchiveCog(commands.Cog):
    """Persist messages and reaction events to Postgres."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: asyncpg.Pool | None = None
        self.enabled = os.getenv("ARCHIVE_MESSAGES") == "1"

    async def cog_load(self) -> None:
        if not self.enabled:
            return
        try:
            self.pool = await get_pool()
        except RuntimeError:
            log.warning("ARCHIVE_MESSAGES set but PG_DSN is missing")
            self.enabled = False
            return
        log.info("Message archival enabled")

    async def cog_unload(self) -> None:
        self.pool = None

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Record existing guild and channel info when the bot starts."""
        if not self.enabled:
            return
        for guild in self.bot.guilds:
            await self._upsert_guild(guild)
            for ch in getattr(guild, "channels", []):
                await self._upsert_channel(ch)

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        if not self.enabled:
            return
        await self._upsert_guild(guild)
        for ch in guild.channels:
            await self._upsert_channel(ch)

    async def _upsert_user(self, member: discord.abc.User) -> int:
        if not self.pool:
            return 0
        flags = getattr(member, "public_flags", None)
        flags_value = getattr(flags, "value", None) if flags is not None else None
        inserted = await self.pool.fetchval(
            """
            INSERT INTO discord."user" (
                user_id, username, discriminator, avatar_hash, is_bot,
                display_name, global_name, banner_hash, accent_color,
                avatar_decoration_hash, system, public_flags,
                first_seen_at, last_seen_at
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12, now(), now())
            ON CONFLICT (user_id)
            DO UPDATE SET
                username=$2,
                discriminator=$3,
                avatar_hash=$4,
                is_bot=$5,
                display_name=$6,
                global_name=$7,
                banner_hash=$8,
                accent_color=$9,
                avatar_decoration_hash=$10,
                system=$11,
                public_flags=$12,
                last_seen_at=EXCLUDED.last_seen_at
            RETURNING xmax = 0
            """,
            member.id,
            member.name,
            getattr(member, "discriminator", None),
            getattr(member, "avatar", None) and member.avatar.key,
            getattr(member, "bot", False),
            getattr(member, "display_name", None),
            getattr(member, "global_name", None),
            getattr(getattr(member, "banner", None), "key", None),
            getattr(member, "accent_color", None),
            getattr(getattr(member, "avatar_decoration", None), "key", None),
            getattr(member, "system", False),
            flags_value,
        )
        return int(bool(inserted))

    async def _upsert_guild(self, guild: discord.Guild) -> int:
        if not self.pool:
            return 0
        inserted = await self.pool.fetchval(
            """
            INSERT INTO discord.guild (guild_id, name, owner_id, created_at)
            VALUES ($1,$2,$3,$4)
            ON CONFLICT (guild_id)
            DO UPDATE SET name=$2, owner_id=$3, updated_at=now()
            RETURNING xmax = 0
            """,
            guild.id,
            guild.name,
            getattr(guild.owner, "id", None),
            guild.created_at,
        )
        return int(bool(inserted))

    async def _upsert_channel(self, channel: discord.abc.GuildChannel) -> int:
        if not self.pool:
            return 0
        guild_id = getattr(channel.guild, "id", None)
        privacy_kind = _privacy_kind(channel)
        inserted = await self.pool.fetchval(
            """
            INSERT INTO discord.channel (
                channel_id, guild_id, name, type, position, parent_id,
                topic, nsfw, rate_limit_per_user, last_message_id,
                bitrate, user_limit, created_at, last_message_at,
                privacy_kind
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
            ON CONFLICT (channel_id)
            DO UPDATE SET
                name=$3,
                type=$4,
                position=$5,
                parent_id=$6,
                topic=$7,
                nsfw=$8,
                rate_limit_per_user=$9,
                last_message_id=$10,
                bitrate=$11,
                user_limit=$12,
                last_message_at=$14,
                privacy_kind=$15
            RETURNING xmax = 0
            """,
            channel.id,
            guild_id,
            getattr(channel, "name", None),
            getattr(channel, "type", None).value if hasattr(channel, "type") else None,
            getattr(channel, "position", None),
            getattr(channel, "category_id", None),
            getattr(channel, "topic", None),
            getattr(channel, "nsfw", None),
            getattr(channel, "rate_limit_per_user", None),
            getattr(channel, "last_message_id", None),
            getattr(channel, "bitrate", None),
            getattr(channel, "user_limit", None),
            getattr(channel, "created_at", None),
            discord.utils.utcnow(),
            privacy_kind,
        )
        return int(bool(inserted))

    async def _insert_message(self, message: discord.Message) -> tuple[int, int]:
        if not self.pool:
            return 0, 0
        payload = (
            json.loads(message.to_json()) if hasattr(message, "to_json") else {}
        )
        reply_to_id = getattr(message.reference, "message_id", None)
        if reply_to_id:
            exists = await self.pool.fetchval(
                "SELECT 1 FROM discord.message WHERE message_id=$1",
                reply_to_id,
            )
            if not exists:
                reply_to_id = None

        msg_tag = await self.pool.execute(
            """
            INSERT INTO discord.message (
                message_id, guild_id, channel_id, author_id, reply_to_id,
                content, created_at, edited_at, pinned, tts, type, flags,
                mention_everyone, mentions, mention_roles, embeds,
                raw_payload)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
            ON CONFLICT DO NOTHING
            """,
            message.id,
            getattr(message.guild, "id", None),
            message.channel.id,
            message.author.id,
            reply_to_id,
            message.content,
            message.created_at,
            message.edited_at,
            message.pinned,
            message.tts,
            int(message.type.value),
            getattr(message.flags, "value", 0),
            getattr(message, "mention_everyone", False),
            json.dumps(getattr(message, "raw_mentions", [])),
            json.dumps(getattr(message, "raw_role_mentions", [])),
            json.dumps([getattr(e, "to_dict", lambda: {})() for e in message.embeds]),
            json.dumps(payload),
        )
        msg_count = rows_from_tag(msg_tag)
        att_count = 0
        for idx, att in enumerate(message.attachments):
            att_tag = await self.pool.execute(
                """
                INSERT INTO discord.message_attachment (
                    message_id, attachment_id, filename, content_type, size_bytes, url, proxy_url)
                VALUES ($1,$2,$3,$4,$5,$6,$7)
                ON CONFLICT DO NOTHING
                """,
                message.id,
                idx,
                att.filename,
                att.content_type,
                att.size,
                att.url,
                att.proxy_url,
            )
            att_count += rows_from_tag(att_tag)

        await self.pool.execute(
            "UPDATE discord.channel SET last_message_id=$1, last_message_at=$2 WHERE channel_id=$3",
            message.id,
            message.created_at,
            message.channel.id,
        )
        return msg_count, att_count

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not self.enabled or message.guild is None:
            return
        await self._upsert_user(message.author)
        await self._upsert_guild(message.guild)
        await self._upsert_channel(message.channel)
        await self._insert_message(message)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if not self.enabled or after.guild is None or not self.pool:
            return
        await self.pool.execute(
            """UPDATE discord.message SET content=$1, edited_at=$2, flags=$3, mention_everyone=$4, mentions=$5, mention_roles=$6, embeds=$7, raw_payload=$8 WHERE message_id=$9""",
            after.content,
            after.edited_at,
            getattr(after.flags, "value", 0),
            getattr(after, "mention_everyone", False),
            json.dumps(getattr(after, "raw_mentions", [])),
            json.dumps(getattr(after, "raw_role_mentions", [])),
            json.dumps([getattr(e, "to_dict", lambda: {})() for e in after.embeds]),
            json.dumps(
                json.loads(after.to_json()) if hasattr(after, "to_json") else {}
            ),
            after.id,
        )

    async def _log_reaction(
        self, payload: discord.RawReactionActionEvent, action: ReactionAction
    ) -> None:
        if not self.pool:
            return
        # Ignore events for messages that are not archived yet
        exists = await self.pool.fetchval(
            "SELECT 1 FROM discord.message WHERE message_id=$1",
            payload.message_id,
        )
        if not exists:
            return
        await self.pool.execute(
            """
            INSERT INTO discord.reaction_event (message_id, user_id, emoji, reaction_action, event_at)
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT ON CONSTRAINT uniq_reaction_event_msg_user_emoji_act_ts DO NOTHING
            """,
            payload.message_id,
            payload.user_id,
            str(payload.emoji),
            action.name,
            discord.utils.utcnow(),
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if not self.enabled:
            return
        await self._log_reaction(payload, ReactionAction.MESSAGE_REACTION_ADD)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if not self.enabled:
            return
        await self._log_reaction(payload, ReactionAction.MESSAGE_REACTION_REMOVE)


async def setup(bot: commands.Bot):
    await bot.add_cog(MessageArchiveCog(bot))

