"""VibeCheckCog - summarize recent server activity with a vibe score.

Implements the `/vibecheck` slash command which looks back 24 hours of
messages and produces a short summary embed with a vibe label, stats and
an AI generated one-liner.
"""
from __future__ import annotations

import re
import time
import asyncio
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands
from ..util import chan_name
from .. import bot_config as cfg
from ..llm.router import router, SafetyBlocked
from ..infra.quotas import RateLimited

# Use a hierarchical logger so messages propagate to the main gentlebot logger
log = logging.getLogger(f"gentlebot.{__name__}")


UNICODE_EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\U00002600-\U000026FF\U00002700-\U000027BF]"
)
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")


def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(val, hi))


class VibeCheckCog(commands.Cog):
    """Slash command `/vibecheck` returning a quick vibe read."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.max_tokens = 60
        self.temperature = 0.6
        self._cache: tuple[float, discord.Embed] | None = None

    # --- scoring helpers -------------------------------------------------
    @staticmethod
    def score_to_label(score: float) -> tuple[str, str]:
        table = [
            (80, "Chaos Gremlin", "🤯"),
            (60, "Hype Train", "🚂"),
            (40, "Cozy Chill", "🛋️"),
            (20, "Quiet Focus", "🤫"),
            (0, "Dead Server", "🌵"),
        ]
        for threshold, label, emoji in table:
            if score >= threshold:
                return label, emoji
        return "Dead Server", "🌵"

    async def _generate_blurb(self, data: str) -> str | None:
        prompt = (
            "You are Gentlebot, a cheeky but concise Discord concierge. "
            "Write ONE or TWO sentences describing the vibe in this server. "
            "Add one emoji. No line breaks.\nDATA:\n" + data
        )
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    router.generate,
                    "general",
                    [{"role": "user", "content": prompt}],
                    self.temperature,
                ),
                timeout=8,
            )
        except asyncio.TimeoutError:
            log.error("Model blurb timed out")
            return None
        except RateLimited:
            return "Let me get back to you on this... I'm a bit busy right now."
        except SafetyBlocked:
            return "Your inquiry is being blocked by my policy commitments."
        except Exception as e:
            log.exception("Model blurb failed: %s", e)
            return None

    async def _collect_stats(self) -> dict:
        guild = self.bot.get_guild(cfg.GUILD_ID)
        if not guild:
            return {}
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=24)
        msg_count = 0
        users: set[int] = set()
        channels: set[int] = set()
        emoji_ctr: Counter[str] = Counter()
        caps = 0
        exclam = 0
        links = 0
        top_msg: discord.Message | None = None
        top_reacts = 0
        for channel in guild.text_channels:
            perms = channel.permissions_for(guild.me)
            if not (perms.read_messages and perms.read_message_history):
                continue
            try:
                async for msg in channel.history(limit=None, after=since):
                    if msg_count >= 2000:
                        break
                    msg_count += 1
                    users.add(msg.author.id)
                    channels.add(channel.id)
                    text = msg.content or ""
                    if text:
                        if sum(c.isupper() for c in text if c.isalpha()) > 0.5 * sum(
                            c.isalpha() for c in text
                        ):
                            caps += 1
                        if "!" in text:
                            exclam += 1
                        if "http" in text:
                            links += 1
                        for e in CUSTOM_EMOJI_RE.findall(text):
                            emoji_ctr[e] += 1
                        for e in UNICODE_EMOJI_RE.findall(text):
                            emoji_ctr[e] += 1
                    reacts = sum(r.count for r in msg.reactions)
                    if reacts > top_reacts and text:
                        top_reacts = reacts
                        top_msg = msg
                if msg_count >= 2000:
                    break
            except discord.Forbidden as e:
                log.warning("History fetch forbidden for %s: %s", chan_name(channel), e)
            except Exception as e:
                log.exception("History fetch failed for %s: %s", chan_name(channel), e)
        caps_ratio = caps / msg_count if msg_count else 0
        exc_ratio = exclam / msg_count if msg_count else 0
        link_ratio = links / msg_count if msg_count else 0
        top_emojis = [e for e, _ in emoji_ctr.most_common(3)]
        quote = ""
        author = ""
        if top_msg:
            quote = top_msg.content.strip().replace("\n", " ")[:120]
            author = top_msg.author.display_name
        return {
            "msg_count": msg_count,
            "unique_users": len(users),
            "active_channels": len(channels),
            "caps_ratio": caps_ratio,
            "exc_ratio": exc_ratio,
            "link_ratio": link_ratio,
            "top_emojis": top_emojis,
            "quote": quote,
            "quote_author": author,
        }

    @staticmethod
    def _compute_score(data: dict) -> float:
        energy = min(data["msg_count"] / 20, 25)
        spread = min(data["active_channels"] * 4, 15)
        crowd = min(data["unique_users"] * 2, 20)
        chaos = (data["caps_ratio"] * 15) + (data["exc_ratio"] * 15)
        brainy = data["link_ratio"] * 10
        return clamp(energy + spread + crowd + chaos + brainy, 0, 100)

    @app_commands.command(name="vibecheck", description="Check the server vibe")
    async def vibecheck(self, interaction: discord.Interaction):
        """Return a quick read on how things feel in the server."""
        log.info("/vibecheck invoked by %s in %s", interaction.user.id, chan_name(interaction.channel))
        now = time.time()
        if self._cache and now - self._cache[0] < 60:
            await interaction.response.send_message(embed=self._cache[1])
            return
        await interaction.response.defer(thinking=True)
        data = await self._collect_stats()
        if not data:
            await interaction.followup.send("Could not read history.")
            return
        score = self._compute_score(data)
        if data["msg_count"] < 20 and data["unique_users"] < 5:
            label, emoji = "Dead Server", "🌵"
        else:
            label, emoji = self.score_to_label(score)
        e1, e2, e3 = (data["top_emojis"] + ["", "", ""])[:3]
        quote_line = f'"{data["quote"]}" – {data["quote_author"]}' if data["quote"] else ""
        blurb_data = (
            f"messages:{data['msg_count']} users:{data['unique_users']} "
            f"channels:{data['active_channels']} caps_ratio:{data['caps_ratio']:.2f} "
            f"exc_ratio:{data['exc_ratio']:.2f} link_ratio:{data['link_ratio']:.2f}\n"
            f"Top emojis: {e1} {e2} {e3}\nQuote: \"{data['quote']}\" – {data['quote_author']}"
        )
        blurb = await self._generate_blurb(blurb_data)
        lines = [f"Overall: **{label}** ({int(score)}/100) {emoji}"]
        if blurb:
            lines.append(f"> {blurb}")
        lines.append("")
        lines.append("Stats:")
        lines.append(f"• Messages: {data['msg_count']}")
        lines.append(f"• Active users: {data['unique_users']}")
        lines.append(f"• Active channels: {data['active_channels']}")
        lines.append(f"• Top emojis: {e1} {e2} {e3}")
        if quote_line:
            lines.append(f"Quote of the day: {quote_line}")
        embed = discord.Embed(title="Current Gentlefolk Vibes", description="\n".join(lines))
        await interaction.followup.send(embed=embed)
        self._cache = (time.time(), embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(VibeCheckCog(bot))
