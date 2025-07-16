"""Archive Discord messages and reactions to Postgres."""
from __future__ import annotations

import json
import logging
import os
import asyncpg
import discord
from discord.ext import commands
from util import build_db_url

log = logging.getLogger(f"gentlebot.{__name__}")


class MessageArchiveCog(commands.Cog):
    """Persist messages and reaction events to Postgres."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool: asyncpg.Pool | None = None
        self.enabled = os.getenv("ARCHIVE_MESSAGES") == "1"

    async def cog_load(self) -> None:
        if not self.enabled:
            return
        url = self._build_db_url()
        if not url:
            log.warning("ARCHIVE_MESSAGES set but DATABASE_URL is missing")
            self.enabled = False
            return
        url = url.replace("postgresql+asyncpg://", "postgresql://")

        async def _init(conn: asyncpg.Connection) -> None:
            await conn.execute("SET search_path=discord,public")

        self.pool = await asyncpg.create_pool(url, init=_init)
        log.info("Message archival enabled")

    async def cog_unload(self) -> None:
        if self.pool:
            await self.pool.close()
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

    @staticmethod
    def _build_db_url() -> str | None:
        return build_db_url()

    async def _upsert_user(self, member: discord.abc.User) -> None:
        if not self.pool:
            return
        await self.pool.execute(
            """
            INSERT INTO discord."user" (
                user_id, username, discriminator, avatar_hash, is_bot,
                display_name, first_seen_at, last_seen_at
            )
            VALUES ($1,$2,$3,$4,$5,$6, now(), now())
            ON CONFLICT (user_id)
            DO UPDATE SET
                username=$2,
                discriminator=$3,
                avatar_hash=$4,
                is_bot=$5,
                display_name=$6,
                last_seen_at=EXCLUDED.last_seen_at
            """,
            member.id,
            member.name,
            getattr(member, "discriminator", None),
            getattr(member, "avatar", None) and member.avatar.key,
            getattr(member, "bot", False),
            getattr(member, "display_name", None),
        )

    async def _upsert_guild(self, guild: discord.Guild) -> None:
        if not self.pool:
            return
        await self.pool.execute(
            """
            INSERT INTO discord.guild (guild_id, name, owner_id, created_at)
            VALUES ($1,$2,$3,$4)
            ON CONFLICT (guild_id)
            DO UPDATE SET name=$2, owner_id=$3, updated_at=now()
            """,
            guild.id,
            guild.name,
            getattr(guild.owner, "id", None),
            guild.created_at,
        )

    async def _upsert_channel(self, channel: discord.abc.GuildChannel) -> None:
        if not self.pool:
            return
        guild_id = getattr(channel.guild, "id", None)
        await self.pool.execute(
            """
            INSERT INTO discord.channel (channel_id, guild_id, name, type, created_at, last_message_at)
            VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (channel_id)
            DO UPDATE SET name=$3, type=$4, last_message_at=$6
            """,
            channel.id,
            guild_id,
            getattr(channel, "name", None),
            getattr(channel, "type", None).value if hasattr(channel, "type") else None,
            getattr(channel, "created_at", None),
            discord.utils.utcnow(),
        )

    async def _insert_message(self, message: discord.Message) -> None:
        if not self.pool:
            return
        payload = (
            json.loads(message.to_json()) if hasattr(message, "to_json") else {}
        )
        await self.pool.execute(
            """
            INSERT INTO discord.message (
                message_id, guild_id, channel_id, author_id, reply_to_id,
                content, created_at, edited_at, pinned, tts, type, raw_payload)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            ON CONFLICT DO NOTHING
            """,
            message.id,
            getattr(message.guild, "id", None),
            message.channel.id,
            message.author.id,
            getattr(message.reference, "message_id", None),
            message.content,
            message.created_at,
            message.edited_at,
            message.pinned,
            message.tts,
            int(message.type.value),
            json.dumps(payload),
        )
        for idx, att in enumerate(message.attachments):
            await self.pool.execute(
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
            """UPDATE discord.message SET content=$1, edited_at=$2, raw_payload=$3 WHERE message_id=$4""",
            after.content,
            after.edited_at,
            json.dumps(
                json.loads(after.to_json()) if hasattr(after, "to_json") else {}
            ),
            after.id,
        )

    async def _log_reaction(self, payload: discord.RawReactionActionEvent, action: int) -> None:
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
            INSERT INTO discord.reaction_event (message_id, user_id, emoji, action, event_at)
            VALUES ($1,$2,$3,$4,$5)
            """,
            payload.message_id,
            payload.user_id,
            str(payload.emoji),
            action,
            discord.utils.utcnow(),
        )

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if not self.enabled:
            return
        await self._log_reaction(payload, 0)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if not self.enabled:
            return
        await self._log_reaction(payload, 1)


async def setup(bot: commands.Bot):
    await bot.add_cog(MessageArchiveCog(bot))

