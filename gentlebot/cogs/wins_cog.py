"""
wins_cog.py – #wins Channel Moderation for Gentlebot
====================================================
Maintains #wins as a reliably positive space for celebrations.

Features:
  • Auto-reacts to celebratory messages with celebration emojis
  • Detects non-celebratory messages using keyword analysis
  • Gently redirects off-topic messages to #lobby
  • Never deletes messages - just guides behavior

Culture rules for #wins:
  • Only celebrations, milestones, good news
  • Responses are encouragement only
  • No advice-giving, no "but have you considered..."

Configuration in bot_config.py:
  • WINS_CHANNEL_ID: channel ID for #wins (0 = disabled)
  • LOBBY_CHANNEL_ID: channel ID for #lobby (redirect target)
"""
from __future__ import annotations
import logging
import random
import re
from discord.ext import commands
import discord
from .. import bot_config as cfg

log = logging.getLogger(f"gentlebot.{__name__}")


# ════════════════════════════════════════════════════════════════════════════
# CELEBRATION DETECTION
# ════════════════════════════════════════════════════════════════════════════

# Emojis the bot uses to celebrate wins
CELEBRATION_EMOJIS = ["🎉", "🥳", "👏", "💪", "⭐", "🔥", "✨", "🏆", "💯", "🙌"]

# Keywords that strongly indicate a celebration/win
CELEBRATION_KEYWORDS = {
    # Direct win words
    "won", "win", "winning", "victory", "success", "successful",
    # Achievement words
    "achieved", "accomplished", "completed", "finished", "nailed",
    "crushed", "smashed", "killed it", "knocked it out",
    # Milestone words
    "milestone", "promoted", "promotion", "raise", "hired", "got the job",
    "accepted", "approved", "passed", "graduated", "certified",
    # Personal wins
    "proud", "excited", "thrilled", "stoked", "pumped", "hyped",
    "finally", "at last", "did it", "made it",
    # Good news patterns
    "good news", "great news", "amazing news", "best news",
    "guess what", "holy shit", "omg", "lets go", "let's go",
    # Celebration expressions
    "celebrate", "celebrating", "woo", "woohoo", "yay", "yess", "yesss",
    "hell yeah", "heck yeah", "boom",
    # Life milestones
    "engaged", "married", "pregnant", "baby", "born", "bought a house",
    "new job", "new car", "moved in", "moved out",
    # Health wins
    "recovered", "clean", "sober", "healthy", "remission",
    # Fitness wins
    "pr", "personal best", "pb", "new record", "beat my",
}

# Keywords that indicate non-celebratory content
NON_CELEBRATION_KEYWORDS = {
    # Questions
    "?", "anyone know", "does anyone", "how do i", "what should",
    "help me", "need help", "struggling with", "having trouble",
    # Negative emotions
    "frustrated", "annoyed", "angry", "upset", "disappointed", "sad",
    "depressed", "anxious", "stressed", "overwhelmed", "exhausted",
    "tired of", "sick of", "hate", "sucks", "terrible", "awful",
    # Complaints
    "rant", "venting", "vent", "complain", "complaint",
    # Seeking advice
    "advice", "thoughts on", "opinions on", "what do you think",
    "should i", "would you",
    # Sharing problems
    "problem", "issue", "bug", "broken", "failed", "failing",
    "lost", "losing", "can't", "cannot", "won't",
}

# Patterns that are clearly celebrations (regex)
CELEBRATION_PATTERNS = [
    r"^(i|we)\s+(got|did|made|won|passed|finished)",  # "I got...", "We won..."
    r"finally\s+\w+",  # "finally passed", "finally done"
    r"just\s+(got|landed|received|heard)",  # "just got promoted"
    r"(🎉|🥳|👏|💪|⭐|🔥|✨|🏆|💯|🙌)",  # Contains celebration emojis
]

# Patterns that are clearly NOT celebrations
NON_CELEBRATION_PATTERNS = [
    r"\?$",  # Ends with question mark
    r"^(anyone|does anyone|has anyone|is there)",  # Asking the group
    r"^(help|advice|thoughts)",  # Seeking help
    r"(ugh|argh|fml|smh)",  # Frustration expressions
]


def is_celebration(text: str) -> tuple[bool, float]:
    """
    Analyze text to determine if it's a celebration.

    Returns:
        (is_celebration, confidence)
        - is_celebration: True if the message appears to be celebratory
        - confidence: 0.0-1.0 indicating how confident we are
    """
    text_lower = text.lower()

    # Check for celebration emojis first (strong signal)
    has_celebration_emoji = any(emoji in text for emoji in CELEBRATION_EMOJIS)

    # Count keyword matches
    celebration_matches = sum(1 for kw in CELEBRATION_KEYWORDS if kw in text_lower)
    non_celebration_matches = sum(1 for kw in NON_CELEBRATION_KEYWORDS if kw in text_lower)

    # Check patterns
    has_celebration_pattern = any(
        re.search(pattern, text_lower) for pattern in CELEBRATION_PATTERNS
    )
    has_non_celebration_pattern = any(
        re.search(pattern, text_lower) for pattern in NON_CELEBRATION_PATTERNS
    )

    # Scoring
    score = 0.5  # Neutral starting point

    # Emoji signals
    if has_celebration_emoji:
        score += 0.3

    # Keyword signals
    score += celebration_matches * 0.15
    score -= non_celebration_matches * 0.2

    # Pattern signals
    if has_celebration_pattern:
        score += 0.25
    if has_non_celebration_pattern:
        score -= 0.3

    # Clamp to [0, 1]
    score = max(0.0, min(1.0, score))

    # Decision threshold
    is_win = score >= 0.5
    confidence = abs(score - 0.5) * 2  # Convert to confidence (0-1)

    return (is_win, confidence)


class WinsCog(commands.Cog):
    """
    Moderates the #wins channel to maintain it as a positive celebration space.

    - Auto-reacts to celebratory messages
    - Gently redirects non-celebratory content to #lobby
    - Never deletes messages, just guides behavior
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.wins_channel_id = getattr(cfg, "WINS_CHANNEL_ID", 0)
        self.lobby_channel_id = getattr(cfg, "LOBBY_CHANNEL_ID", 0)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Process messages in the #wins channel."""
        # Ignore bots
        if message.author.bot:
            return

        # Only process messages in #wins
        if not self.wins_channel_id or message.channel.id != self.wins_channel_id:
            return

        # Skip very short messages or messages with only emojis/media
        text = message.content.strip()
        if len(text) < 3:
            # Short message - likely a response. Auto-react if it has positive emojis
            if any(emoji in text for emoji in CELEBRATION_EMOJIS):
                await self._add_celebration_reaction(message)
            return

        # Analyze the message
        is_win, confidence = is_celebration(text)

        log.debug(
            "wins analysis for %s: is_win=%s, confidence=%.2f, text='%s'",
            message.author,
            is_win,
            confidence,
            text[:50],
        )

        if is_win:
            # It's a celebration! Add some reactions
            await self._add_celebration_reaction(message)
        else:
            # Not a celebration - gently redirect if we're confident
            if confidence > 0.3:  # Only redirect if reasonably confident
                await self._gentle_redirect(message)

    async def _add_celebration_reaction(self, message: discord.Message) -> None:
        """Add celebration emoji reactions to a message."""
        # Pick 1-2 random celebration emojis
        emojis = random.sample(CELEBRATION_EMOJIS, k=random.randint(1, 2))
        for emoji in emojis:
            try:
                await message.add_reaction(emoji)
            except discord.HTTPException:
                pass  # Ignore reaction failures

    async def _gentle_redirect(self, message: discord.Message) -> None:
        """
        Send a gentle redirect message for non-celebratory content.

        The redirect is:
        - Friendly and non-punitive
        - Ephemeral (only visible to the author) when possible
        - Suggests #lobby as an alternative
        """
        lobby_mention = f"<#{self.lobby_channel_id}>" if self.lobby_channel_id else "#lobby"

        # Friendly redirect messages (randomized to feel less robotic)
        redirects = [
            f"Hey {message.author.mention}! This channel is our wins-only zone 🎉 "
            f"For general chat, {lobby_mention} would be perfect!",

            f"Psst {message.author.mention} — #wins is just for celebrations! "
            f"Feel free to drop this in {lobby_mention} instead 💬",

            f"Quick heads up {message.author.mention}: #wins is reserved for good news and celebrations 🏆 "
            f"Try {lobby_mention} for this one!",
        ]

        redirect_message = random.choice(redirects)

        try:
            # Reply to the message
            reply = await message.reply(redirect_message, mention_author=False)

            # Auto-delete the redirect after 30 seconds to reduce clutter
            await reply.delete(delay=30)

            log.info(
                "Redirected non-celebratory message from %s in #wins",
                message.author,
            )
        except discord.HTTPException as e:
            log.warning("Failed to send redirect message: %s", e)

    @commands.command(name='wins_test')
    async def wins_test(self, ctx: commands.Context, *, text: str):
        """Test the celebration detection on a given message."""
        is_win, confidence = is_celebration(text)
        result = "✅ CELEBRATION" if is_win else "❌ NOT A CELEBRATION"
        await ctx.send(
            f"**Analysis**: {result}\n"
            f"**Confidence**: {confidence:.0%}\n"
            f"**Text**: {text[:100]}..."
        )

    @commands.command(name='wins_stats')
    async def wins_stats(self, ctx: commands.Context):
        """Show #wins channel configuration."""
        wins_status = "enabled" if self.wins_channel_id else "disabled"
        lobby_status = f"<#{self.lobby_channel_id}>" if self.lobby_channel_id else "not set"

        await ctx.send(
            f"**#wins Moderation Stats**\n"
            f"• Status: {wins_status}\n"
            f"• Wins channel: <#{self.wins_channel_id}>\n"
            f"• Redirect target: {lobby_status}\n"
            f"• Celebration keywords: {len(CELEBRATION_KEYWORDS)}\n"
            f"• Non-celebration keywords: {len(NON_CELEBRATION_KEYWORDS)}"
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(WinsCog(bot))
