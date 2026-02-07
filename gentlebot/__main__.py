"""Entry point to run the Gentlebot Discord bot."""
import asyncio
import logging
import os
import argparse
import dataclasses
import json
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from . import bot_config as cfg
from .postgres_handler import PostgresHandler
from .github_handler import GitHubIssueHandler
from .infra.github_issues import get_github_issue_config
from .util import build_db_url
from .db import close_pool
from .version import get_version
from .capabilities import CapabilityRegistry

# ─── Logging Setup ─────────────────────────────────────────────────────────
logger = logging.getLogger("gentlebot")
level_name = os.getenv("LOG_LEVEL", "INFO").upper()
level = getattr(logging, level_name, logging.INFO)
logger.setLevel(level)
log_format = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_format)
# Limit console output to INFO and above even when file logging is DEBUG
console_handler.setLevel(logging.INFO)

root_logger = logging.getLogger()
root_logger.setLevel(level)
root_logger.addHandler(console_handler)

# Suppress noisy CommandNotFound errors from the app command tree
class _IgnoreMissingCommand(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        return not isinstance(exc, app_commands.CommandNotFound)


logging.getLogger("discord.app_commands.tree").addFilter(
    _IgnoreMissingCommand()
)

logger.info(
    "Starting GentleBot in %s environment with level %s",
    getattr(cfg, "env", "PROD"),
    level_name,
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True  # RoleCog needs this
intents.presences = True

class GentleBot(commands.Bot):
    async def setup_hook(self) -> None:
        # Load cogs bundled with the package
        cog_dir = Path(__file__).resolve().parent / "cogs"
        failed_cogs = []
        for file in cog_dir.glob("*_cog.py"):
            if file.stem == "test_logging_cog" and not cfg.IS_TEST:
                continue
            try:
                await self.load_extension(f"gentlebot.cogs.{file.stem}")
            except Exception as exc:
                logger.exception("Failed to load cog %s: %s", file.stem, exc)
                failed_cogs.append(file.stem)
        if failed_cogs:
            logger.warning("Bot starting with failed cogs: %s", failed_cogs)

        # Initialize capability registry after all cogs are loaded
        self.capability_registry = CapabilityRegistry(self)
        await self.capability_registry.discover()


bot = GentleBot(command_prefix="!", intents=intents)

_synced = False
_backfills_started = False
_backfill_tasks: list[asyncio.Task] = []

@bot.event
async def on_ready() -> None:
    global _synced, _backfills_started
    logger.info("%s is now online in this guild", bot.user)
    if not _synced:
        try:
            cmds = await bot.tree.sync()
            logger.info("Synced %d commands.", len(cmds))
            _synced = True
        except Exception as e:
            logger.exception("Failed to sync commands: %s", e)
    if not _backfills_started:
        _backfills_started = True
        days = int(os.getenv("BACKFILL_DAYS", "30"))
        from . import (
            backfill_archive,
            backfill_commands,
            backfill_reactions,
            backfill_roles,
        )

        async def _run_backfills() -> None:
            backfills = [
                ("commands", backfill_commands.run_backfill, days),
                ("archive", backfill_archive.run_backfill, days),
                ("reactions", backfill_reactions.run_backfill, days),
                ("roles", backfill_roles.run_backfill, None),
            ]

            for i, (name, func, arg) in enumerate(backfills):
                try:
                    if arg is None:
                        await func()
                    else:
                        await func(arg)
                except Exception:
                    logger.exception("Backfill %s failed", name)
                if i < len(backfills) - 1:
                    await asyncio.sleep(5)

        _backfill_tasks.append(asyncio.create_task(_run_backfills()))

@bot.event
async def on_error(event: str, *args, **kwargs) -> None:
    logger.exception("Unhandled exception in event %s", event)

@bot.event
async def on_command_error(
    ctx: commands.Context, exc: commands.CommandError
) -> None:
    if isinstance(exc, commands.CommandNotFound):
        return
    logger.exception("Error in command '%s'", getattr(ctx.command, 'name', 'unknown'), exc_info=exc)

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction, exc: discord.app_commands.AppCommandError
) -> None:
    cmd_name = getattr(interaction.command, "name", "unknown")
    logger.exception("Error in slash command '%s'", cmd_name, exc_info=exc)
    if interaction.response.is_done():
        await interaction.followup.send("An error occurred.", ephemeral=True)
    else:
        await interaction.response.send_message("An error occurred.", ephemeral=True)

async def main() -> None:
    db_url = build_db_url()
    db_handler = None
    file_handler = None
    github_handler = None

    if db_url:
        db_handler = PostgresHandler(db_url)
        await db_handler.connect()
        root_logger.addHandler(db_handler)
        logger.info("Postgres logging enabled; file logging disabled")
    else:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            log_dir / "bot.log", when="midnight", backupCount=90
        )
        file_handler.setFormatter(log_format)
        root_logger.addHandler(file_handler)

    # Initialize GitHub issue handler (PROD only)
    github_config = get_github_issue_config()
    env = os.getenv("env", "PROD").upper()
    if github_config.enabled and env == "PROD":
        github_handler = GitHubIssueHandler(github_config)
        await github_handler.connect()
        root_logger.addHandler(github_handler)
        logger.info("GitHub issue handler enabled for error reporting")

    try:
        async with bot:
            await bot.start(cfg.TOKEN)
    finally:
        # Cancel and await backfill tasks for clean shutdown
        for task in _backfill_tasks:
            if not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(task, timeout=5.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass
                except Exception:
                    logger.exception("Error awaiting backfill task")
        _backfill_tasks.clear()

        if github_handler:
            github_handler.close()
        if db_handler:
            await db_handler.aclose()
        if file_handler:
            file_handler.close()
        await close_pool()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Gentlebot")
    subparsers = parser.add_subparsers(dest="command")
    parser.add_argument("--version", action="version", version=get_version())

    prompt_parser = subparsers.add_parser(
        "generate-prompt", help="Generate and persist a daily prompt"
    )
    prompt_parser.add_argument("--date", help="Target date (YYYY-MM-DD)")
    prompt_parser.add_argument("--config", help="Path to prompt config YAML")
    prompt_parser.add_argument("--state", help="Path to SQLite state file")

    args = parser.parse_args()
    if args.command == "generate-prompt":
        from .cli import _parse_date
        from .tasks.daily_prompt_composer import DailyPromptComposer

        date = _parse_date(args.date)
        with DailyPromptComposer(config_path=args.config, state_path=args.state) as composer:
            prompt = composer.generate_prompt(date=date)
            print(json.dumps(dataclasses.asdict(prompt), indent=2, default=str))
    else:
        asyncio.run(main())
