"""
Capability Discovery and Registry for Gentlebot
================================================

This module provides a dynamic capability discovery system that generates
Gentlebot's "self-awareness" prompt automatically from cog metadata.

## How It Works

1. **At startup**, the CapabilityRegistry iterates over all loaded cogs
2. **Auto-discovers** slash commands via `bot.tree.get_commands()`
3. **Reads CAPABILITIES** class attributes from cogs for rich metadata
4. **Generates** a formatted prompt listing all features

## Why This Approach?

Previously, `gemini_cog.py` maintained a hardcoded `CAPABILITIES_PROMPT` that
would fall out of sync with actual features. This hybrid approach:

- **Auto-validates**: Commands must exist to appear in the prompt
- **Rich metadata**: Cogs can declare reactions, scheduled tasks, categories
- **Easy maintenance**: Add CAPABILITIES to your cog, and it's auto-included

## Usage

In your cog, add a CAPABILITIES class attribute:

```python
from gentlebot.capabilities import (
    CogCapabilities, CommandCapability, Category
)

class MyCog(commands.Cog):
    CAPABILITIES = CogCapabilities(
        commands=[
            CommandCapability(
                name="mycommand",
                description="/mycommand <arg> - Does something useful",
                category=Category.GENERAL,
            ),
        ]
    )
```

See `gentlebot/cogs/AGENTS.md` for full documentation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discord.ext.commands import Bot

log = logging.getLogger(f"gentlebot.{__name__}")


class Category(Enum):
    """Categories for organizing bot capabilities in the prompt."""

    GENERAL = "General"
    SPORTS = "Sports"
    MARKETS = "Markets"
    COMMUNITY = "Community"
    ENGAGEMENT = "Engagement"
    SCHEDULED_DAILY = "Daily"
    SCHEDULED_WEEKLY = "Weekly"
    SCHEDULED_LIVE = "Live Events"


@dataclass
class CommandCapability:
    """Metadata for a slash command.

    Attributes:
        name: The command name (without slash), e.g., "celebrate"
        description: Rich description for the prompt, e.g., "/celebrate @user - Celebrate someone"
        category: Category for grouping in the prompt
        admin_only: If True, marked as admin-only in the prompt
    """

    name: str
    description: str
    category: Category
    admin_only: bool = False


@dataclass
class ReactionCapability:
    """Metadata for a reaction-triggered feature.

    Attributes:
        emoji: The emoji that triggers this feature, e.g., "📋"
        trigger: What triggers the reaction, e.g., "Shared links"
        description: What happens when the reaction is used
        channel_restriction: Optional channel name where this works, e.g., "#reading"
    """

    emoji: str
    trigger: str
    description: str
    channel_restriction: str | None = None


@dataclass
class ScheduledCapability:
    """Metadata for a scheduled/automatic feature.

    Attributes:
        name: Display name for the feature, e.g., "Daily Digest"
        schedule: Human-readable schedule, e.g., "8:30 AM PT"
        description: What this scheduled task does
        category: Category (typically SCHEDULED_DAILY, SCHEDULED_WEEKLY, or SCHEDULED_LIVE)
    """

    name: str
    schedule: str
    description: str
    category: Category


@dataclass
class CogCapabilities:
    """Container for all capabilities declared by a cog.

    A cog can have any combination of commands, reactions, and scheduled tasks.
    All fields default to empty lists if not provided.

    Example:
        CAPABILITIES = CogCapabilities(
            commands=[CommandCapability(...)],
            reactions=[ReactionCapability(...)],
            scheduled=[ScheduledCapability(...)],
        )
    """

    commands: list[CommandCapability] = field(default_factory=list)
    reactions: list[ReactionCapability] = field(default_factory=list)
    scheduled: list[ScheduledCapability] = field(default_factory=list)


class CapabilityRegistry:
    """Discovers and organizes bot capabilities for self-awareness prompts.

    This registry is initialized after all cogs are loaded and provides
    a dynamically generated capabilities prompt for the LLM.
    """

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self._commands: list[CommandCapability] = []
        self._reactions: list[ReactionCapability] = []
        self._scheduled: list[ScheduledCapability] = []
        self._discovered_command_names: set[str] = set()

    async def discover(self) -> None:
        """Discover all capabilities from loaded cogs.

        This should be called once after all cogs are loaded in setup_hook().
        It will:
        1. Get all registered slash commands from bot.tree
        2. Read CAPABILITIES from each cog
        3. Validate that declared commands actually exist
        """
        # Get all registered command names for validation
        self._discovered_command_names = {
            cmd.name for cmd in self.bot.tree.get_commands()
        }

        log.info(
            "Discovered %d slash commands: %s",
            len(self._discovered_command_names),
            sorted(self._discovered_command_names),
        )

        # Iterate over loaded cogs and collect CAPABILITIES
        for cog_name, cog in self.bot.cogs.items():
            capabilities = getattr(cog, "CAPABILITIES", None)
            if not isinstance(capabilities, CogCapabilities):
                continue

            log.debug("Processing CAPABILITIES from %s", cog_name)

            # Collect commands (validate they exist)
            for cmd_cap in capabilities.commands:
                if cmd_cap.name in self._discovered_command_names:
                    self._commands.append(cmd_cap)
                else:
                    log.warning(
                        "Cog %s declares command '%s' but it's not registered",
                        cog_name,
                        cmd_cap.name,
                    )

            # Collect reactions (no validation needed)
            self._reactions.extend(capabilities.reactions)

            # Collect scheduled tasks (no validation needed)
            self._scheduled.extend(capabilities.scheduled)

        log.info(
            "Capability registry: %d commands, %d reactions, %d scheduled",
            len(self._commands),
            len(self._reactions),
            len(self._scheduled),
        )

    def generate_prompt(self) -> str:
        """Generate the capabilities prompt for the LLM system prompt.

        Returns a formatted markdown string describing all bot capabilities,
        organized by category.
        """
        sections = []

        # Header
        sections.append("# YOUR CAPABILITIES")
        sections.append("")
        sections.append(
            "You are Gentlebot, the Discord copilot for the Gentlefolk community. "
            "You have access to tools and can guide users to your slash commands "
            "and scheduled features."
        )

        # Tools section (static - these are LLM tools, not Discord commands)
        sections.append("")
        sections.append("## TOOLS (use these during conversation)")
        sections.append("")
        sections.append("**web_search(query, max_results?)**")
        sections.append("- Search the web for current information, news, recent events")
        sections.append("- Use for: live scores, recent news, weather, current events")
        sections.append("")
        sections.append("**calculate(expression)**")
        sections.append("- Evaluate math: arithmetic, percentages, sqrt, log, trig")
        sections.append("- Use for ANY math beyond simple addition")
        sections.append("")
        sections.append("**read_file(path, limit?, offset?)**")
        sections.append("- Read Gentlebot codebase for context or citations")
        sections.append("")
        sections.append("**generate_image(prompt)**")
        sections.append("- Generate an image using Gemini's image model")
        sections.append("- The image will be attached to your response")
        sections.append("")
        sections.append("**When to use tools:** current events, math, code questions, image requests")
        sections.append("**When NOT to use:** casual chat, opinions, general knowledge")

        # Slash commands section
        if self._commands:
            sections.append("")
            sections.append("## SLASH COMMANDS (guide users to these)")
            sections.append("")

            # Group by category
            by_category: dict[Category, list[CommandCapability]] = {}
            for cmd in self._commands:
                by_category.setdefault(cmd.category, []).append(cmd)

            # Order categories logically
            category_order = [
                Category.GENERAL,
                Category.SPORTS,
                Category.MARKETS,
                Category.COMMUNITY,
                Category.ENGAGEMENT,
            ]

            for cat in category_order:
                if cat not in by_category:
                    continue
                sections.append(f"**{cat.value}:**")
                for cmd in sorted(by_category[cat], key=lambda c: c.name):
                    suffix = " (admin only)" if cmd.admin_only else ""
                    sections.append(f"- {cmd.description}{suffix}")
                sections.append("")

        # Reaction features section
        if self._reactions:
            sections.append("## REACTION FEATURES")
            sections.append("")
            for rxn in self._reactions:
                channel_note = f" (in {rxn.channel_restriction})" if rxn.channel_restriction else ""
                sections.append(f"- {rxn.emoji} {rxn.trigger}{channel_note}: {rxn.description}")
            sections.append("")

        # Scheduled features section
        if self._scheduled:
            sections.append("## SCHEDULED FEATURES (automatic)")
            sections.append("")

            # Group by category
            by_category: dict[Category, list[ScheduledCapability]] = {}
            for sched in self._scheduled:
                by_category.setdefault(sched.category, []).append(sched)

            schedule_order = [
                Category.SCHEDULED_DAILY,
                Category.SCHEDULED_WEEKLY,
                Category.SCHEDULED_LIVE,
            ]

            for cat in schedule_order:
                if cat not in by_category:
                    continue
                sections.append(f"**{cat.value}:**")
                for sched in by_category[cat]:
                    sections.append(f"- {sched.schedule} — {sched.name}: {sched.description}")
                sections.append("")

        # User interaction section
        sections.append("## HOW USERS CAN INTERACT WITH YOU")
        sections.append("")
        sections.append("1. **Mention me:** @Gentlebot followed by a question")
        sections.append("2. **Reply to me:** Reply to any of my messages")
        sections.append("3. **DM me:** Send a direct message")
        sections.append("4. **Use /ask:** The slash command for questions")
        sections.append("")
        sections.append(
            "I respond with tools when helpful, react to messages occasionally, "
            "and try to be concise but informative."
        )

        return "\n".join(sections)


def get_default_capabilities() -> str:
    """Return a fallback capabilities prompt when registry is unavailable.

    This is used during bot startup before the registry is initialized,
    or if the registry fails to initialize.
    """
    return """# YOUR CAPABILITIES

You are Gentlebot, the Discord copilot for the Gentlefolk community.
You have access to tools and can guide users to your slash commands.

Use /ask to ask me anything. I'm still warming up, so my full feature list
will be available shortly.
"""
