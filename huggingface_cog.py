# cogs/huggingface_cog.py

import os
import re
import time
import random
import asyncio
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands
from huggingface_hub import InferenceClient


class HuggingFaceCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # === Env/config ===
        self.hf_api_key = os.getenv("HF_API_TOKEN")
        self.model_id = os.getenv("HF_MODEL", "meta-llama/Meta-Llama-3-8B-Instruct")
        self.max_tokens = int(os.getenv("HF_MAX_TOKENS", 200))
        self.temperature = float(os.getenv("HF_TEMPERATURE", 0.8))
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
        self.base_reaction_chance = 0.02  # 2% chance per message by default
        self.mention_reaction_chance = 0.45  # 45% chance when content mentions "gentlebot"
        # static fallback unicode emojis
        self.default_emojis = ["😂", "🤔", "😅", "🔥", "🙃", "😎"]

        # === Ambient response chance ===
        self.ambient_chance = 0.005  # 0.5% chance to respond without prompt

    @commands.Cog.listener()
    async def on_ready(self):
        bot_id = self.bot.user.id
        self.mention_strs = [f"<@{bot_id}>", f"<@!{bot_id}>" ]
        # Register slash command and sync
        try:
            self.bot.tree.add_command(self.ask)
            await self.bot.tree.sync()
            print("[HuggingFaceCog] Slash commands synced on ready.")
        except Exception as e:
            print(f"[HuggingFaceCog] Error syncing slash commands: {e}")
        print(f"[HuggingFaceCog] Ready. mention_strs={self.mention_strs}")

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

    async def call_hf(self, channel_id: int, user_prompt: str) -> str:
        """
        Build context with recent history + system directive, send to HF, update history.
        """
        history = self.histories[channel_id]

        system_directive = (
            "Please keep your response under 1900 characters to fit Discord's limits. "
            "Finish your response with a complete sentence before stopping. Do not ask follow-up questions in your response. "
            "Your personality should be that of a robot butler with an almost imperceptibly subtle sardonic wit."
        )
        messages = []
        messages.extend(history[-(self.max_turns * 2):])
        messages.append({"role": "system", "content": system_directive})
        messages.append({"role": "user", "content": user_prompt})

        completion = self.hf_client.chat.completions.create(
            model=self.model_id,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            top_p=self.top_p
        )

        reply = getattr(completion.choices[0].message, "content", "").strip()

        history.append({"role": "user", "content": user_prompt})
        history.append({"role": "assistant", "content": reply})
        if len(history) > self.max_turns * 2:
            self.histories[channel_id] = history[-(self.max_turns * 2):]

        return reply

    async def choose_emoji_hf(self, message_content: str, available_emojis: list[str]) -> str | None:
        """
        Ask the HF model to select an emoji from the provided available_emojis list that humorously reacts to the message_content.
        Returns the selected emoji string from available_emojis, or None on failure.
        """
        emoji_list_str = ", ".join(available_emojis)
        prompt = (
            f"Here is a list of emojis available in the server: {emoji_list_str}. "
            f"Select one emoji from this list that best expresses how a robotic butler with a sardonic wit would react to the following message: '{message_content}'. Respond only with the emoji."
        )
        try:
            # Use dummy channel to avoid polluting histories
            response = await self.call_hf(0, prompt)
            for emoji in available_emojis:
                if emoji in response:
                    return emoji
            return None
        except Exception:
            return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # 1) Ignore bots
        if message.author.bot:
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
            except Exception:
                pass

        # 4) Ensure mention_strs initialized
        if not self.mention_strs:
            return

        prompt = None

        # 5) Direct mention: strip mention
        parts = content.split()
        if parts and parts[0] in self.mention_strs:
            raw = content
            for mention in self.mention_strs:
                if raw.startswith(mention):
                    raw = raw.replace(mention, "", 1).strip()
                    break
            prompt = raw
        elif message.reference and isinstance(message.reference.resolved, discord.Message):
            ref_msg = message.reference.resolved
            if ref_msg.author.id == self.bot.user.id:
                prompt = content
        # 6) Ambient response: rare chance if not directed
        elif random.random() < self.ambient_chance:
            prompt = content

        if not prompt:
            return

        # 7) Rate‑limit per user: wait instead of immediate reply
        now = time.time()
        last = self.cooldowns[message.author.id]
        elapsed = now - last
        if elapsed < self.cooldown_seconds:
            wait_time = self.cooldown_seconds - elapsed
            await asyncio.sleep(wait_time)
        self.cooldowns[message.author.id] = time.time()

                # 8) Sanitize prompt with awareness of ambient jump
        if "prompt" in locals() and prompt:
            if 'ambient_chance' in dir(self) and prompt == content and 'gentlebot' not in content.lower() and not (parts and parts[0] in self.mention_strs) and not (message.reference and isinstance(message.reference.resolved, discord.Message) and message.reference.resolved.author.id == self.bot.user.id):
                # Ambient jump: prepend context note
                user_prompt = f"You are unexpectedly inserting yourself into an ongoing conversation. The message you're reacting to is: '{prompt}'. Be concise."
            else:
                user_prompt = prompt
        else:
            return
        sanitized = self.sanitize_prompt(user_prompt)
        if sanitized is None:
            await message.reply("❌ Invalid prompt: too long, empty, or disallowed mentions.")
            return

        # 9) Typing indicator while fetching while fetching
        async with message.channel.typing():
            try:
                response = await self.call_hf(message.channel.id, sanitized)
            except Exception as e:
                await message.reply(f"⚠️ HuggingFace error: {e}")
                return

        # 10) Paginate if needed
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
        await interaction.response.defer()
        sanitized = self.sanitize_prompt(prompt)
        if not sanitized:
            return await interaction.followup.send("❌ Prompt invalid: too long or contains disallowed mentions.")
        response = await self.call_hf(interaction.channel_id, sanitized)
        if len(response) <= 2000:
            await interaction.followup.send(response)
        else:
            for chunk in [response[i : i + 1900] for i in range(0, len(response), 1900)]:
                await interaction.followup.send(chunk)

async def setup(bot: commands.Bot):
    await bot.add_cog(HuggingFaceCog(bot))