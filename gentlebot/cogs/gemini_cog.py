"""Gemini-powered conversational responses and emoji reactions."""

import re
import time
import random
import asyncio
import logging
from collections import defaultdict
from datetime import timedelta

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands
from ..util import chan_name, user_name
from ..llm.router import router, SafetyBlocked
from ..infra.quotas import RateLimited
from ..db import get_pool


# Use a hierarchical logger so messages propagate to the main gentlebot logger
log = logging.getLogger(f"gentlebot.{__name__}")


class GeminiCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # === Env/config ===
        self.max_tokens = 150
        self.temperature = 0.6

        # === Mention strings (populated after on_ready) ===
        self.mention_strs: list[str] = []

        # === Conversation memory: channel_id → list of {role, content} ===
        self.histories: dict[int, list[dict]] = defaultdict(list)
        self.max_turns = 19  # keep last N user+assistant turns

        # === Rate‑limiting: user_id → last_timestamp ===
        self.cooldowns: dict[int, float] = defaultdict(lambda: 0)
        self.cooldown_seconds = 10

        # === Sanitization rules ===
        self.MAX_PROMPT_LEN = 750
        self.DISALLOWED_PATTERN = re.compile(r"<@&\d+>")  # e.g. guild roles
        self.MENTION_CLEANUP = re.compile(r"<@!?(\d+)>")  # strip user mentions

        # === Emoji reaction settings ===
        self.base_reaction_chance = 0.02  # 2% chance per message by default
        self.mention_reaction_chance = 0.25  # 45% chance when content mentions "gentlebot"
        # static fallback unicode emojis
        self.default_emojis = ["😂", "🤔", "😅", "🔥", "🙃", "😎"]

        # === Ambient response chance ===
        self.ambient_chance = 0  # ambient message responses disabled

        # === Database pool for archived messages ===
        self.pool: asyncpg.Pool | None = None

    @commands.Cog.listener()
    async def on_ready(self):
        bot_id = self.bot.user.id
        self.mention_strs = [f"<@{bot_id}>", f"<@!{bot_id}>"]
        log.info("Ready to interact with the guild.")

    async def cog_load(self) -> None:
        """Initialize database pool for message archive retrieval."""
        try:
            self.pool = await get_pool()
        except RuntimeError:
            self.pool = None
            log.warning("GeminiCog disabled archive due to missing database URL")

    def strip_mentions(self, raw: str) -> str:
        """Replace user mentions with names, drop role mentions, collapse blanks."""

        def repl(match: re.Match) -> str:
            uid = int(match.group(1))
            user = self.bot.get_user(uid)
            return f"@{user_name(user) if user else uid}"

        text = self.MENTION_CLEANUP.sub(repl, raw)
        text = self.DISALLOWED_PATTERN.sub("", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def sanitize_prompt(self, raw: str) -> str | None:
        """Validate user prompts before sending to the model."""
        if len(raw) > self.MAX_PROMPT_LEN:
            return None

        if self.DISALLOWED_PATTERN.search(raw):
            return None

        prompt = self.strip_mentions(raw)

        if not prompt:
            return None

        return prompt


    async def call_llm(self, channel_id: int, user_prompt: str) -> str:
        """Send chat history to Gemini and return the reply."""
        channel = self.bot.get_channel(channel_id)

        history = self.histories[channel_id]

        system_directive = (
            "Speak like a helpful and concise robot interacting with a Discord server of friends."
        )

        messages = []
        messages.extend(history[-(self.max_turns * 2):])
        messages.append({"role": "system", "content": system_directive})
        messages.append({"role": "user", "content": user_prompt})

        try:
            reply = await asyncio.to_thread(
                router.generate, "general", messages, self.temperature
            )
        except RateLimited:
            return "Let me get back to you on this... I'm a bit busy right now."
        except SafetyBlocked:
            return "Your inquiry is being blocked by my policy commitments."
        except Exception:
            log.exception("Model call failed")
            return "Something's wrong... I need a mechanic."

        history.append({"role": "user", "content": user_prompt})
        history.append({"role": "assistant", "content": reply})
        if len(history) > self.max_turns * 2:
            self.histories[channel_id] = history[-(self.max_turns * 2):]

        log.info("Model response in channel %s: %s", chan_name(channel), reply)
        return reply

    async def _get_context_from_archive(self, channel_id: int) -> str:
        """Return messages from the last 24h in the given channel."""
        if not self.pool:
            return ""
        since = discord.utils.utcnow() - timedelta(hours=24)
        try:
            rows = await self.pool.fetch(
                """
                SELECT m.content, u.display_name
                  FROM discord.message m
                  JOIN discord."user" u ON m.author_id = u.user_id
                 WHERE m.channel_id=$1 AND m.created_at >= $2
                 ORDER BY m.created_at ASC LIMIT 50
                """,
                channel_id,
                since,
            )
        except Exception:
            log.exception("Archive fetch failed")
            return ""
        lines = []
        for r in rows:
            content = r["content"]
            author = r["display_name"] or "?"
            if content:
                lines.append(f"{author}: {content}")
        return "\n".join(lines)

    async def choose_emoji_llm(self, message_content: str, custom_emojis: list[str]) -> str | None:
        """
        Ask the Gemini model to select either a standard emoji or one of the
        provided custom_emojis that humorously reacts to the message_content.
        Returns the chosen emoji string or ``None`` on failure.
        """
        custom_list = ", ".join(custom_emojis) if custom_emojis else ""
        prompt = (
            "You may react using any standard emoji or one of these custom"
            f" emojis: {custom_list}. Select a single emoji that best expresses"
            f" how a friendly person would react to the following message:"
            f" '{message_content}'. Respond only with the emoji."
        )
        try:
            # Use dummy channel to avoid polluting histories
            response = (await self.call_llm(0, prompt)).strip()
            for emoji in custom_emojis:
                if emoji in response:
                    return emoji
            return response.split()[0] if response else None
        except Exception as e:
            log.exception("Gemini emoji selection failed: %s", e)
            return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 1) Ignore bots
        if message.author.bot:
            return

        # 1a) Ignore ephemeral messages to avoid reaction errors
        if getattr(message.flags, "ephemeral", False):
            return

        content = message.content.strip()

        # 2) Determine reaction probability
        if "gentlebot" in content.lower():
            chance = self.mention_reaction_chance
        else:
            chance = self.base_reaction_chance

        # 3) React based on chance
        if random.random() < chance:
            custom = [str(e) for e in message.guild.emojis] if message.guild and message.guild.emojis else []
            emoji_resp = await self.choose_emoji_llm(message.content, custom)
            pool = custom + self.default_emojis
            emoji_to_use = emoji_resp if emoji_resp else random.choice(pool)
            try:
                await message.add_reaction(emoji_to_use)
            except Exception as e:
                log.exception("Failed to add reaction: %s", e)

        # 4) Ensure mention_strs initialized
        if not self.mention_strs:
            return

        prompt = None
        parts = content.split()
        mention_starts_message = bool(parts and parts[0] in self.mention_strs)

        # 5) Direct mention anywhere: strip mention(s) but keep entire text
        if any(m in content for m in self.mention_strs):
            raw = content
            for mention in self.mention_strs:
                raw = raw.replace(mention, "").strip()
            prompt = raw
        # 6) Reply to bot: treat as prompt
        elif message.reference and isinstance(message.reference.resolved, discord.Message):
            ref_msg = message.reference.resolved
            if ref_msg.author.id == self.bot.user.id:
                prompt = content

        if not prompt and not mention_starts_message:
            return

        # 7) Rate‑limit per user: wait instead of immediate reply
        now = time.time()
        last = self.cooldowns[message.author.id]
        elapsed = now - last
        if elapsed < self.cooldown_seconds:
            wait_time = self.cooldown_seconds - elapsed
            await asyncio.sleep(wait_time)
        self.cooldowns[message.author.id] = time.time()

        # 8) Sanitize user prompt
        sanitized_prompt = self.sanitize_prompt(prompt)
        if sanitized_prompt is None:
            if mention_starts_message:
                requester = user_name(message.author)
                sanitized_prompt = (
                    f"{requester} pinged you directly but didn't add any other text. "
                    "Respond with a short friendly acknowledgment and invite them to share what they need."
                )
            else:
                log.info("Rejected prompt: too long, empty, or disallowed mentions.")
                return

        # 9) Build user_prompt with optional context
        is_ambient = (
            prompt == content
            and 'gentlebot' not in content.lower()
            and not mention_starts_message
            and not (message.reference and isinstance(message.reference.resolved, discord.Message) and message.reference.resolved.author.id == self.bot.user.id)
        )
        if is_ambient:
            recent_msgs = []
            async for m in message.channel.history(limit=10):
                if m.id != message.id and not m.author.bot:
                    recent_msgs.append(m.content.strip())
            recent_msgs.reverse()
            context_str = self.strip_mentions("\n".join(recent_msgs))
            prefix = (
                "You are jumping into an ongoing conversation that people probably don't want you involved in. Here are the last few messages:\n"
            )
            suffix = f"\nNow react to the message: '{sanitized_prompt}'"
            max_context = self.MAX_PROMPT_LEN - len(prefix) - len(suffix)
            if context_str and max_context > 0:
                context_part = context_str[-max_context:]
                user_prompt = f"{prefix}{context_part}{suffix}"
            else:
                user_prompt = sanitized_prompt
        else:
            context_str = self.strip_mentions(await self._get_context_from_archive(message.channel.id))
            prefix = "Recent conversation within the last 24 hours:\n"
            suffix = f"\n\nUser message: {sanitized_prompt}"
            max_context = self.MAX_PROMPT_LEN - len(prefix) - len(suffix)
            if context_str and max_context > 0:
                context_part = context_str[-max_context:]
                user_prompt = f"{prefix}{context_part}{suffix}"
            else:
                user_prompt = sanitized_prompt

        # 10) Typing indicator while fetching
        async with message.channel.typing():
            try:
                response = await self.call_llm(message.channel.id, user_prompt)
            except Exception as e:
                log.exception("Model call failed: %s", e)
                return

        # 11) Replace placeholder mentions and send, paginating if needed
        response = re.sub(r"@User\b", message.author.mention, response)
        if len(response) <= 2000:
            await message.reply(response, mention_author=True)
        else:
            chunks = [response[i : i + 1900] for i in range(0, len(response), 1900)]
            for chunk in chunks:
                await message.reply(chunk, mention_author=True)

    # === Slash command /ask ===
    @app_commands.command(name="ask", description="Ask Gentlebot a question.")
    async def ask(self, interaction: discord.Interaction, prompt: str):
        """Slash command to ask Gentlebot a question."""
        log.info("/ask invoked by %s in %s", user_name(interaction.user), chan_name(interaction.channel))
        await interaction.response.defer()
        sanitized = self.sanitize_prompt(prompt)
        if not sanitized:
            log.info("Rejected prompt for /ask: too long, empty, or disallowed mentions.")
            return
        try:
                response = await self.call_llm(interaction.channel_id, sanitized)
        except Exception as e:
            log.exception("Model call failed in /ask: %s", e)
            return

        if len(response) <= 2000:
            await interaction.followup.send(response)
        else:
            for chunk in [response[i : i + 1900] for i in range(0, len(response), 1900)]:
                await interaction.followup.send(chunk)

async def setup(bot: commands.Bot):
    await bot.add_cog(GeminiCog(bot))
