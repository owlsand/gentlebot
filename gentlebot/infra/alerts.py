"""Alerting system for task failures and critical errors.

This module provides a simple mechanism to send Discord DMs to configured
operators when scheduled tasks fail or critical errors occur.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Literal

import discord
from discord.ext.commands import Bot

log = logging.getLogger(f"gentlebot.{__name__}")

# Comma-separated list of Discord user IDs to receive alerts
ALERT_USER_IDS: list[int] = [
    int(uid.strip())
    for uid in os.getenv("ALERT_USER_IDS", "").split(",")
    if uid.strip().isdigit()
]

Severity = Literal["error", "warning", "info"]

SEVERITY_EMOJI: dict[Severity, str] = {
    "error": "\U0001f6a8",  # 🚨
    "warning": "\u26a0\ufe0f",  # ⚠️
    "info": "\u2139\ufe0f",  # ℹ️
}


async def send_alert(
    bot: Bot,
    title: str,
    message: str,
    severity: Severity = "error",
    *,
    context: dict[str, str] | None = None,
) -> int:
    """Send an alert to configured operators.

    Args:
        bot: The Discord bot instance.
        title: Short title for the alert.
        message: Detailed message describing the issue.
        severity: Alert severity level ("error", "warning", or "info").
        context: Optional dictionary of additional context (task name, etc.).

    Returns:
        Number of users successfully notified.

    Example::

        await send_alert(
            bot,
            "Daily Digest Failed",
            "Could not assign roles: HTTPException",
            severity="error",
            context={"task": "daily_digest", "guild_id": "12345"},
        )
    """
    if not ALERT_USER_IDS:
        log.debug("No alert recipients configured; skipping alert: %s", title)
        return 0

    emoji = SEVERITY_EMOJI.get(severity, SEVERITY_EMOJI["info"])
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Build the alert message
    lines = [
        f"{emoji} **{title}**",
        "",
        message,
    ]

    if context:
        lines.append("")
        lines.append("**Context:**")
        for key, value in context.items():
            lines.append(f"• {key}: `{value}`")

    lines.append("")
    lines.append(f"*{timestamp}*")

    alert_text = "\n".join(lines)

    # Truncate if too long
    if len(alert_text) > 1900:
        alert_text = alert_text[:1900] + "\n... (truncated)"

    sent_count = 0
    for user_id in ALERT_USER_IDS:
        try:
            user = await bot.fetch_user(user_id)
            await user.send(alert_text)
            sent_count += 1
            log.debug("Sent alert to user %s: %s", user_id, title)
        except discord.NotFound:
            log.warning("Alert recipient %s not found", user_id)
        except discord.Forbidden:
            log.warning("Cannot DM alert recipient %s (DMs disabled)", user_id)
        except discord.HTTPException as exc:
            log.warning("Failed to send alert to %s: %s", user_id, exc)
        except Exception:
            log.exception("Unexpected error sending alert to %s", user_id)

    if sent_count == 0 and ALERT_USER_IDS:
        log.warning("Failed to send alert to any recipient: %s", title)

    return sent_count


async def alert_task_failure(
    bot: Bot,
    task_name: str,
    error: Exception | str,
    *,
    context: dict[str, str] | None = None,
) -> int:
    """Convenience function for alerting on task failures.

    Args:
        bot: The Discord bot instance.
        task_name: Name of the failed task.
        error: The exception or error message.
        context: Optional additional context.

    Returns:
        Number of users notified.
    """
    error_msg = str(error)
    if len(error_msg) > 500:
        error_msg = error_msg[:500] + "..."

    full_context = {"task": task_name}
    if context:
        full_context.update(context)

    return await send_alert(
        bot,
        f"Task Failed: {task_name}",
        f"```\n{error_msg}\n```",
        severity="error",
        context=full_context,
    )


def get_alert_recipients() -> list[int]:
    """Return the list of configured alert recipient user IDs."""
    return ALERT_USER_IDS.copy()


def is_alerting_enabled() -> bool:
    """Return True if alerting is configured with at least one recipient."""
    return len(ALERT_USER_IDS) > 0
