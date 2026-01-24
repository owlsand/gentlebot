"""Gemini-powered conversational responses and emoji reactions."""

import io
import re
import time
import random
import asyncio
import inspect
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands
from ..util import chan_name, user_name
from ..llm.router import SafetyBlocked, SYSTEM_INSTRUCTION, router, get_router
from ..llm.tokenizer import estimate_tokens, truncate_to_token_budget
from ..infra.quotas import RateLimited
from ..db import get_pool


# Capability awareness section for the system prompt
CAPABILITIES_PROMPT = """
# YOUR CAPABILITIES

You are Gentlebot, the Discord copilot for the Gentlefolk community. You have access to tools and can guide users to your slash commands and scheduled features.

## TOOLS (use these during conversation)

**web_search(query, max_results?)**
- Search the web for current information, news, recent events
- Use for: live scores, recent news, weather, current events
- Example: "What's the current score of the Seahawks game?"

**calculate(expression)**
- Evaluate math: arithmetic, percentages, sqrt, log, trig
- Use for ANY math beyond simple addition
- Example: calculate("847 * 0.15") for "15% of 847"

**read_file(path, limit?, offset?)**
- Read Gentlebot codebase for context or citations
- Use when discussing how Gentlebot works

**generate_image(prompt)**
- Generate an image using Gemini's image model
- The image will be attached to your response
- Use for: drawing requests, visualizations, creative images
- Be detailed in your prompt for better results

**When to use tools:** current events, math, code questions, image requests
**When NOT to use:** casual chat, opinions, general knowledge

## SLASH COMMANDS (guide users to these)

**General:**
- `/ask <prompt>` — Ask me anything (this command!)
- `/imagine <prompt>` — Generate an image using Gemini
- `/version` — Show my current version
- `/gentlebot <message>` — Make me say something (admin only)

**Sports:**
- `/bigdumper [style]` — Cal Raleigh stats and latest homer
- `/nextf1` — Next F1 race weekend preview with track map
- `/f1standings` — Current F1 driver & constructor standings

**Markets:**
- `/stock <symbol> <period>` — Stock chart + key stats (1d to 10y)
- `/earnings <symbol>` — Next earnings date for a ticker
- `/marketmood` — US market sentiment snapshot
- `/marketbet [direction]` — Weekly bull/bear prediction game

**Community:**
- `/vibecheck` — Summarize server vibes (uses AI)
- `/engagement [time_window] [chart]` — Guild engagement stats
- `/catchup [scope] [style]` — Summarize what you missed
- `/techmeme` — Latest Techmeme tech headlines
- `/refreshroles` — Rotate engagement badges (admin only)

## SCHEDULED FEATURES (automatic)

**Daily:**
- 🌅 8:30 AM PT — Daily Digest: Awards Daily Hero, Top Poster, Reaction Magnet roles
- 📨 9:00 AM PT — Daily Hero DM: Personalized message to today's hero
- 🎋 10:00 PM PT — Daily Haiku: AI-generated haiku from the day's chat

**Weekly:**
- 📊 Monday 9:00 AM — Weekly VibeCheck: Server sentiment report
- 📈 Monday 7:00 AM — Market Bet Reminder: DM to place predictions
- 💰 Friday 1:00 PM — Market Summary: Weekly bet results
- 🏈 Tuesday 9:00 AM — Fantasy Football Recap (during season)

**Live Sports (when games are on):**
- 🏈 Seahawks: Game threads + score updates
- ⚾ Mariners: Game announcements
- 🏎️ F1: Session threads for every race weekend

## HOW USERS CAN INTERACT WITH YOU

1. **Mention me:** @Gentlebot followed by a question
2. **Reply to me:** Reply to any of my messages
3. **DM me:** Send a direct message
4. **Use /ask:** The slash command for questions

I respond with tools when helpful, react to messages occasionally, and try to be concise but informative.
"""


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

        # === Rate‑limiting: user_id → last_timestamp ===
        self.cooldowns: dict[int, float] = defaultdict(lambda: 0)
        self.cooldown_seconds = 10

        # === Sanitization rules ===
        self.MAX_PROMPT_LEN = 4000  # Increased from 750 to allow complex questions
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


    async def _maybe_trigger_typing(self, channel: discord.abc.Messageable) -> None:
        """Best-effort typing indicator that tolerates missing methods."""

        trigger_typing = getattr(channel, "trigger_typing", None)
        if callable(trigger_typing):
            result = trigger_typing()
            if inspect.isawaitable(result):
                await result
            return

        typing_ctx = getattr(channel, "typing", None)
        if callable(typing_ctx):
            try:
                async with typing_ctx():
                    await asyncio.sleep(0)
            except Exception:
                log.debug("Failed to trigger typing indicator", exc_info=True)


    async def _build_chat_history_block(
        self, channel: discord.abc.Messageable | None, exclude: discord.Message | None
    ) -> str:
        """Return a formatted sliding window of recent channel messages."""

        if not channel or not hasattr(channel, "history"):
            return "No recent chat history."

        lines: list[str] = []

        async for msg in channel.history(limit=15):
            if exclude and msg.id == exclude.id:
                continue
            if not msg.content and not msg.attachments:
                continue
            timestamp = msg.created_at.astimezone(timezone.utc).isoformat()
            author = user_name(msg.author)
            content = msg.clean_content.strip()
            if not content and msg.attachments:
                content = ", ".join(att.filename for att in msg.attachments)
            lines.append(f"[{timestamp}] {author}: {content}")

        lines.reverse()
        # Use character-based token estimation (~4 chars per token)
        # This is more accurate than word count for mixed content
        token_lengths = [estimate_tokens(line) for line in lines]
        total_tokens = sum(token_lengths)
        max_context_tokens = 1500  # Increased budget with better estimation
        while lines and total_tokens > max_context_tokens:
            total_tokens -= token_lengths.pop(0)
            lines.pop(0)

        if not lines:
            return "No recent chat history."

        return "\n".join(lines)

    async def _build_system_prompt(
        self,
        channel: discord.abc.Messageable | None,
        user: discord.abc.User | None,
        exclude: discord.Message | None,
    ) -> str:
        """Assemble the system prompt with context and core rules."""

        current_time = datetime.now(timezone.utc).isoformat()

        channel_name = getattr(channel, "name", None) if channel else None
        channel_name = channel_name or "direct-message"
        topic = getattr(channel, "topic", None) or "General"

        user_display = user.display_name if user else "Unknown"
        roles: list[str] = []
        if isinstance(user, discord.Member):
            roles = [r.name for r in user.roles if not r.is_default()]
        user_roles = ", ".join(roles) if roles else "Member"

        history_block = await self._build_chat_history_block(channel, exclude)

        _, _, remainder = SYSTEM_INSTRUCTION.partition("\n")
        core_instructions = remainder.lstrip("\n") if remainder else SYSTEM_INSTRUCTION

        return (
            "You are Gentlebot, a Discord copilot/robot for the Gentlefolk community.\n\n"
            "# CONTEXT LAYER\n"
            f"- **Time:** {current_time}\n"
            f"- **Channel:** #{channel_name} (Topic: {topic})\n"
            f"- **User:** {user_display} (Roles: {user_roles})\n"
            "- **Recent Chat History:**\n"
            f"{history_block}\n\n"
            f"{CAPABILITIES_PROMPT}\n\n"
            "# CORE INSTRUCTIONS\n"
            f"{core_instructions}"
        )

    async def call_llm(
        self,
        channel: discord.abc.Messageable | None,
        user_prompt: str,
        user: discord.abc.User | None = None,
        exclude: discord.Message | None = None,
    ) -> str:
        """Send context-aware prompts to Gemini and return the reply."""

        if isinstance(channel, discord.abc.Messageable):
            system_prompt = await self._build_system_prompt(channel, user, exclude)
        else:
            system_prompt = (
                "Speak like a helpful and concise robot interacting with a Discord "
                "server of friends."
            )

        # Get conversation history from archive for continuity
        channel_id = getattr(channel, "id", 0)
        user_id = user.id if user else 0
        bot_id = self.bot.user.id if self.bot.user else 0

        history = await self._get_conversation_turns(
            channel_id, user_id, bot_id, max_messages=10
        )

        # Build messages: system prompt + conversation history + current message
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)  # Previous turns from archive
        messages.append({"role": "user", "content": user_prompt})

        try:
            reply = await asyncio.to_thread(
                router.generate,
                "general",
                messages,
                self.temperature,
                system_instruction=system_prompt,
            )
        except TypeError as exc:
            if "system_instruction" in str(exc):
                reply = await asyncio.to_thread(
                    router.generate,
                    "general",
                    messages,
                    self.temperature,
                )
            else:
                log.exception("Model call failed")
                return "Something's wrong... I need a mechanic."
        except RateLimited:
            return "Let me get back to you on this... I'm a bit busy right now."
        except SafetyBlocked:
            return "Your inquiry is being blocked by my policy commitments."
        except Exception:
            log.exception("Model call failed")
            return "Something's wrong... I need a mechanic."

        log.info(
            "Model response in channel %s: %s",
            chan_name(channel) if channel else "unknown",
            reply,
        )
        return reply

    async def _invoke_llm(
        self,
        channel: discord.abc.Messageable | None,
        user_prompt: str,
        user: discord.abc.User | None = None,
        exclude: discord.Message | None = None,
    ) -> str:
        """Call the LLM helper while tolerating simplified test doubles."""

        func = self.call_llm
        params = list(inspect.signature(func).parameters.values())
        if params and params[0].name == "self":
            params = params[1:]
        accepts_context = len(params) >= 4 or any(
            p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
            for p in params
        )

        if accepts_context:
            return await func(channel, user_prompt, user, exclude)

        return await func(channel, user_prompt)

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

    async def _get_conversation_turns(
        self,
        channel_id: int,
        user_id: int,
        bot_id: int,
        max_messages: int = 20,
    ) -> list[dict[str, str]]:
        """Get recent conversation turns between user and bot from archive.

        Returns alternating user/assistant messages for LLM context.
        Uses message count (not time) to determine window.
        """
        if not self.pool:
            return []

        try:
            rows = await self.pool.fetch(
                """
                SELECT m.content, m.author_id, m.created_at
                FROM discord.message m
                WHERE m.channel_id = $1
                  AND (
                      m.author_id = $2  -- User's messages
                      OR m.author_id = $3  -- Bot's messages
                  )
                ORDER BY m.created_at DESC
                LIMIT $4
                """,
                channel_id,
                user_id,
                bot_id,
                max_messages,
            )
        except Exception:
            log.exception("Conversation turns fetch failed")
            return []

        # Build messages (reverse to chronological order)
        messages: list[dict[str, str]] = []
        for row in reversed(rows):
            role = "assistant" if row["author_id"] == bot_id else "user"
            content = row["content"]
            if content:
                messages.append({"role": role, "content": content})

        return messages

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
            response = (await self._invoke_llm(None, prompt)).strip()
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
        is_dm = message.guild is None

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
        # 7) DM conversation: treat entire content as prompt
        elif is_dm:
            prompt = content
            mention_starts_message = True

        if not prompt and not mention_starts_message:
            return

        # 8) Rate‑limit per user: wait instead of immediate reply
        now = time.time()
        last = self.cooldowns[message.author.id]
        elapsed = now - last
        if elapsed < self.cooldown_seconds:
            wait_time = self.cooldown_seconds - elapsed
            await asyncio.sleep(wait_time)
        self.cooldowns[message.author.id] = time.time()

        # 9) Sanitize user prompt
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

        await self._maybe_trigger_typing(message.channel)

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
                response = await self._invoke_llm(
                    message.channel, user_prompt, message.author, message
                )
            except Exception as e:
                log.exception("Model call failed: %s", e)
                return

        # 11) Check for pending images from tool calls
        pending_images = get_router().get_pending_images()
        files: list[discord.File] = []
        for idx, (img_prompt, img_data) in enumerate(pending_images):
            filename = f"generated_{idx + 1}.png"
            files.append(discord.File(io.BytesIO(img_data), filename=filename))

        # 12) Replace placeholder mentions and send, paginating if needed
        response = re.sub(r"@User\b", message.author.mention, response)
        if len(response) <= 2000:
            await message.reply(response, files=files if files else None, mention_author=True)
        else:
            chunks = [response[i : i + 1900] for i in range(0, len(response), 1900)]
            for i, chunk in enumerate(chunks):
                # Attach images only to the first chunk
                chunk_files = files if i == 0 and files else None
                await message.reply(chunk, files=chunk_files, mention_author=True)

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
            response = await self._invoke_llm(
                interaction.channel, sanitized, interaction.user
            )
        except Exception as e:
            log.exception("Model call failed in /ask: %s", e)
            return

        # Check for pending images from tool calls
        pending_images = get_router().get_pending_images()
        files: list[discord.File] = []
        for idx, (img_prompt, img_data) in enumerate(pending_images):
            filename = f"generated_{idx + 1}.png"
            files.append(discord.File(io.BytesIO(img_data), filename=filename))

        if len(response) <= 2000:
            await interaction.followup.send(response, files=files if files else None)
        else:
            chunks = [response[i : i + 1900] for i in range(0, len(response), 1900)]
            for i, chunk in enumerate(chunks):
                chunk_files = files if i == 0 and files else None
                await interaction.followup.send(chunk, files=chunk_files)

async def setup(bot: commands.Bot):
    await bot.add_cog(GeminiCog(bot))
