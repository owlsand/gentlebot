# cogs/huggingface_cog.py

import os
import re
import time
import random
import asyncio
import logging
from collections import defaultdict
from requests.exceptions import HTTPError

import discord
from discord import app_commands
from discord.ext import commands
from gentlebot.utils import chan_name
from huggingface_hub import InferenceClient


# Use a hierarchical logger so messages propagate to the main gentlebot logger
log = logging.getLogger(f"gentlebot.{__name__}")


class HuggingFaceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # === Env/config ===
        self.hf_api_key = os.getenv("HF_API_TOKEN")
        # Optional secondary token used if the primary hits a billing error
        self.hf_api_key_alt = os.getenv("HF_API_TOKEN_ALT")
        self._using_alt = False
        self.model_id = os.getenv("HF_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")
        self.max_tokens = int(os.getenv("HF_MAX_TOKENS", 150))
        self.temperature = float(os.getenv("HF_TEMPERATURE", 0.6))
        self.top_p = float(os.getenv("HF_TOP_P", 0.9))

        if not self.hf_api_key:
            raise RuntimeError("HF_API_TOKEN is not set in environment")

        # === Inference client ===
        self.hf_client = InferenceClient(
            api_key=self.hf_api_key,
            provider="together"
        )

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
        self.base_reaction_chance = 0.01  # 2% chance per message by default
        self.mention_reaction_chance = 0.25  # 45% chance when content mentions "gentlebot"
        # static fallback unicode emojis
        self.default_emojis = ["😂", "🤔", "😅", "🔥", "🙃", "😎"]

        # === Ambient response chance ===
        self.ambient_chance = 0.005  # 0.5% chance to respond without prompt

    @commands.Cog.listener()
    async def on_ready(self):
        bot_id = self.bot.user.id
        self.mention_strs = [f"<@{bot_id}>", f"<@!{bot_id}>"]
        log.info("Ready to interact with the guild.")

    def sanitize_prompt(self, raw: str) -> str | None:
        """
        1. Reject if prompt too long.
        2. Reject if it contains a role mention.
        3. Strip all user mentions.
        4. Collapse excessive blank lines.
        """
        if len(raw) > self.MAX_PROMPT_LEN:
            return None

        if self.DISALLOWED_PATTERN.search(raw):
            return None

        prompt = self.MENTION_CLEANUP.sub("", raw).strip()
        prompt = re.sub(r"\n{3,}", "\n\n", prompt)

        if not prompt or prompt.isspace():
            return None

        return prompt

    def friendly_hf_error(self, err: Exception) -> str:
        """Return a user-friendly message for a HuggingFace error."""
        msg = str(err)
        if "Payment Required" in msg:
            return "Apologies, my batteries are low and in need of a recharge."
        if "Too Many Requests" in msg or "429" in msg:
            return "Terribly sorry, I'm processing quite a few tasks. Please try again shortly."
        if "Service Unavailable" in msg or "503" in msg:
            return "My connection to the knowledge chamber faltered. A moment's patience, please."
        return f"⚠️ HuggingFace error: {err}"

    def _is_billing_error(self, err: Exception) -> bool:
        """Return True if the error appears to be billing-related."""
        msg = str(err).lower()
        if (
            "payment required" in msg
            or "payment" in msg
            or "billing" in msg
            or "insufficient" in msg
            or "402" in msg
            or "credit" in msg
            or "quota" in msg
        ):
            return True
        if isinstance(err, HTTPError):
            resp = getattr(err, "response", None)
            if resp is not None and getattr(resp, "status_code", None) == 402:
                return True
        return False

    async def call_hf(self, channel_id: int, user_prompt: str) -> str:
        """
        Build context with channel info + recent history + system directive, send to HF, update history.
        """
        # Fetch channel info for tone adjustment
        channel = self.bot.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            channel_name = channel.name
            channel_topic = channel.topic or "No description"
            channel_info = f"This conversation is happening in the '{channel_name}' channel (topic/description: {channel_topic}). "
        else:
            channel_info = ""

        history = self.histories[channel_id]

        system_directive = (
            f"{channel_info}"
            "Please keep your response under 1900 characters to fit Discord's limits and finish your response with a complete sentence before stopping. "
            "Speak like a helpful British butler from the 1800's (but don't ever reference this directly) with a helpful wit."
            "Adapt your formality to the channel: be more formal in informational channels and more casual in informal channels."
            "Never start your response with filler words or interjections like 'Ah' or 'Well' and never reference physical gestures like 'adjusts cravat'."
            "Be concise and never ask follow-up questions."
        )

        messages = []
        messages.extend(history[-(self.max_turns * 2):])
        messages.append({"role": "system", "content": system_directive})
        messages.append({"role": "user", "content": user_prompt})

        log.debug(
            "Calling HF with %s token", "alternate" if self._using_alt else "primary"
        )

        try:
            completion = self.hf_client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                top_p=self.top_p,
            )
        except Exception as e:
            log.exception("HF call failed with primary token: %s", e)
            if (
                self.hf_api_key_alt
                and not self._using_alt
                and self._is_billing_error(e)
            ):
                log.warning(
                    "Primary HF token hit billing issue; retrying with alternate token"
                )
                self.hf_client = InferenceClient(
                    api_key=self.hf_api_key_alt, provider="together"
                )
                self._using_alt = True
                try:
                    completion = self.hf_client.chat.completions.create(
                        model=self.model_id,
                        messages=messages,
                        max_tokens=self.max_tokens,
                        temperature=self.temperature,
                        top_p=self.top_p,
                    )
                except Exception as alt_e:
                    log.exception("HF call failed with alternate token: %s", alt_e)
                    raise
            else:
                raise

        reply = getattr(completion.choices[0].message, "content", "")

        history.append({"role": "user", "content": user_prompt})
        history.append({"role": "assistant", "content": reply})
        if len(history) > self.max_turns * 2:
            self.histories[channel_id] = history[-(self.max_turns * 2):]

        log.info("Response invoked in channel %s with prompt: %s", chan_name(channel), user_prompt)
        return reply

    async def choose_emoji_hf(self, message_content: str, available_emojis: list[str]) -> str | None:
        """
        Ask the HF model to select an emoji from the provided available_emojis list that humorously reacts to the message_content.
        Returns the selected emoji string from available_emojis, or None on failure.
        """
        emoji_list_str = ", ".join(available_emojis)
        prompt = (
            f"Here is a list of emojis available in the server: {emoji_list_str}. "
            f"Select one emoji from this list that best expresses how a friendly person would react to the following message: '{message_content}'. Respond only with the emoji."
        )
        try:
            # Use dummy channel to avoid polluting histories
            response = await self.call_hf(0, prompt)
            for emoji in available_emojis:
                if emoji in response:
                    return emoji
            return None
        except Exception as e:
            log.exception("HF emoji selection failed: %s", e)
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
            available = []
            if message.guild and message.guild.emojis:
                available.extend(str(e) for e in message.guild.emojis)
            available.extend(self.default_emojis)
            emoji_resp = await self.choose_emoji_hf(message.content, available) if available else None
            emoji_to_use = emoji_resp if emoji_resp else random.choice(available)
            try:
                await message.add_reaction(emoji_to_use)
            except Exception as e:
                log.exception("Failed to add reaction: %s", e)

        # 4) Ensure mention_strs initialized
        if not self.mention_strs:
            return

        prompt = None
        parts = content.split()

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
        # 7) Ambient response: increased chance if 'gentlebot' mentioned, else rare chance
        else:
            if 'gentlebot' in content.lower():
                if random.random() < self.mention_reaction_chance:
                    prompt = content
            elif random.random() < self.ambient_chance:
                prompt = content

        if not prompt:
            return

        # 8) Rate‑limit per user: wait instead of immediate reply
        now = time.time()
        last = self.cooldowns[message.author.id]
        elapsed = now - last
        if elapsed < self.cooldown_seconds:
            wait_time = self.cooldown_seconds - elapsed
            await asyncio.sleep(wait_time)
        self.cooldowns[message.author.id] = time.time()

        # 9) Build user_prompt, including last 10 messages if ambient
        is_ambient = (
            prompt == content
            and 'gentlebot' not in content.lower()
            and not (parts and parts[0] in self.mention_strs)
            and not (message.reference and isinstance(message.reference.resolved, discord.Message) and message.reference.resolved.author.id == self.bot.user.id)
        )
        if is_ambient:
            recent_msgs = []
            async for m in message.channel.history(limit=10):
                if m.id != message.id and not m.author.bot:
                    recent_msgs.append(m.content.strip())
            recent_msgs.reverse()
            context_str = "\n".join(recent_msgs)
            user_prompt = (
                f"You are jumping into an ongoing conversation that people probably don't want you involved in. Here are the last few messages:\n{context_str}\n"
                f"Now react to the message: '{prompt}'"
            )
        else:
            user_prompt = prompt

        # 10) Sanitize prompt
        sanitized = self.sanitize_prompt(user_prompt)
        if sanitized is None:
            await message.reply("❌ Invalid prompt: too long, empty, or disallowed mentions.")
            return

        # 11) Typing indicator while fetching
        async with message.channel.typing():
            try:
                response = await self.call_hf(message.channel.id, sanitized)
            except Exception as e:
                await message.reply(self.friendly_hf_error(e))
                return

        # 12) Paginate if needed
        if len(response) <= 2000:
            await message.reply(response)
        else:
            chunks = [response[i : i + 1900] for i in range(0, len(response), 1900)]
            for chunk in chunks:
                await message.reply(chunk)

    # === Slash command /ask ===
    @app_commands.command(name="ask", description="Ask Gentlebot a question.")
    async def ask(self, interaction: discord.Interaction, prompt: str):
        """Slash command to ask Gentlebot a question."""
        log.info("/ask invoked by %s in %s", interaction.user.id, chan_name(interaction.channel))
        await interaction.response.defer()
        sanitized = self.sanitize_prompt(prompt)
        if not sanitized:
            return await interaction.followup.send("My apologies, I cannot comment.")
        try:
            response = await self.call_hf(interaction.channel_id, sanitized)
        except Exception as e:
            return await interaction.followup.send(self.friendly_hf_error(e))

        if len(response) <= 2000:
            await interaction.followup.send(response)
        else:
            for chunk in [response[i : i + 1900] for i in range(0, len(response), 1900)]:
                await interaction.followup.send(chunk)

async def setup(bot: commands.Bot):
    await bot.add_cog(HuggingFaceCog(bot))
