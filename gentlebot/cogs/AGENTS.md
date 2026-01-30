# Cog Development Guide

This directory houses all feature cogs for Gentlebot. Each file should be
named `*_cog.py` and define one or more `commands.Cog` subclasses.

## Guidelines
- Use a hierarchical logger: `log = logging.getLogger(f"gentlebot.{__name__}")`.
- Keep async Discord responses under 1900 characters.
- Provide a short module-level docstring describing commands.
- Include type hints where practical.
- Add related tests under `tests/`.

---

## Capability Declaration

Every cog should declare a `CAPABILITIES` class attribute so Gentlebot knows
what it can do. This powers the bot's self-awareness when users ask "what can
you do?" and helps keep documentation in sync with actual features.

### Why?

Previously, the capabilities prompt was hardcoded and would fall out of sync
with actual features. Now capabilities are discovered automatically at startup
from cog metadata, ensuring Gentlebot always knows what it can do.

### For Slash Commands

```python
from gentlebot.capabilities import CogCapabilities, CommandCapability, Category

class MyCog(commands.Cog):
    CAPABILITIES = CogCapabilities(
        commands=[
            CommandCapability(
                name="mycommand",              # Without the slash
                description="/mycommand <arg> — Does something useful",
                category=Category.GENERAL,     # See categories below
                admin_only=False,              # Optional, defaults to False
            ),
        ]
    )
```

### For Reaction-Based Features

```python
from gentlebot.capabilities import CogCapabilities, ReactionCapability

class MyCog(commands.Cog):
    CAPABILITIES = CogCapabilities(
        reactions=[
            ReactionCapability(
                emoji="🔔",
                trigger="Reminder requests",   # What triggers the reaction
                description="React with 🔔 to set a reminder",
                channel_restriction="#reminders",  # Optional
            ),
        ]
    )
```

### For Scheduled Tasks

```python
from gentlebot.capabilities import CogCapabilities, ScheduledCapability, Category

class MyCog(commands.Cog):
    CAPABILITIES = CogCapabilities(
        scheduled=[
            ScheduledCapability(
                name="Daily Summary",
                schedule="9:00 AM PT",
                description="Posts a summary of yesterday's activity",
                category=Category.SCHEDULED_DAILY,
            ),
        ]
    )
```

### Available Categories

| Category | Use For |
|----------|---------|
| `Category.GENERAL` | General-purpose commands (`/ask`, `/version`) |
| `Category.SPORTS` | Sports-related commands (`/bigdumper`, `/nextf1`) |
| `Category.MARKETS` | Financial/market commands (`/stock`) |
| `Category.COMMUNITY` | Community engagement (`/vibecheck`, `/trending`) |
| `Category.ENGAGEMENT` | Gamification features (`/streak`, `/celebrate`) |
| `Category.SCHEDULED_DAILY` | Daily automated tasks |
| `Category.SCHEDULED_WEEKLY` | Weekly automated tasks |
| `Category.SCHEDULED_LIVE` | Live event handlers (game threads) |

### Combining Multiple Capability Types

A cog can declare any combination:

```python
CAPABILITIES = CogCapabilities(
    commands=[
        CommandCapability(...),
        CommandCapability(...),
    ],
    reactions=[
        ReactionCapability(...),
    ],
    scheduled=[
        ScheduledCapability(...),
    ],
)
```

### Important Notes

1. **Commands are validated**: If you declare a command in `CAPABILITIES` but
   it's not actually registered as a slash command, a warning is logged.

2. **No CAPABILITIES = no self-description**: Your commands will still work,
   but Gentlebot won't know about them when users ask "what can you do?"

3. **Keep descriptions concise**: The description appears in the LLM prompt,
   so keep it to one line with the key information.

4. **Include parameter hints**: Use `<required>` and `[optional]` in descriptions
   so users know what arguments to provide.

### Example: Complete Cog

```python
"""My feature cog for Gentlebot."""
import logging
from discord import app_commands
from discord.ext import commands

from ..capabilities import CogCapabilities, CommandCapability, Category

log = logging.getLogger(f"gentlebot.{__name__}")


class MyCog(commands.Cog):
    """Provides the /myfeature command."""

    CAPABILITIES = CogCapabilities(
        commands=[
            CommandCapability(
                name="myfeature",
                description="/myfeature <action> [target] — Do something cool",
                category=Category.GENERAL,
            ),
        ]
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="myfeature", description="Do something cool")
    async def myfeature(self, interaction, action: str, target: str = None):
        await interaction.response.send_message(f"Did {action} to {target or 'nothing'}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MyCog(bot))
```
