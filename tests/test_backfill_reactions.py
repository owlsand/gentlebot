import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, PropertyMock, patch

import asyncpg
import discord

from gentlebot.backfill_reactions import BackfillBot, parse_args


def test_parse_args_env(monkeypatch):
    monkeypatch.setenv("BACKFILL_DAYS", "42")
    args = parse_args([])
    assert args.days == 42


def test_backfill_skips_fk_violation():
    """INSERT that hits FK violation should be caught and skipped."""

    async def run_test():
        bot = BackfillBot.__new__(BackfillBot)
        bot.inserted = 0

        pool = AsyncMock()
        pool.execute = AsyncMock(
            side_effect=asyncpg.ForeignKeyViolationError(
                "insert or update on table \"reaction_event\" violates "
                "foreign key constraint"
            )
        )
        bot.pool = pool

        # Minimal stubs for the objects iterated in backfill_history
        user = SimpleNamespace(bot=False, id=1)
        reaction = SimpleNamespace(emoji="👍")
        reaction.users = lambda limit: _async_iter([user])
        msg = SimpleNamespace(
            id=999,
            reactions=[reaction],
            created_at=discord.utils.utcnow(),
        )

        channel = SimpleNamespace(name="test")
        channel.history = lambda limit, after: _async_iter([msg])

        guild = SimpleNamespace(text_channels=[channel])

        with patch.object(
            type(bot), "guilds", new_callable=PropertyMock, return_value=[guild]
        ):
            await bot.backfill_history(1)

        # Should have been caught — inserted stays 0
        assert bot.inserted == 0

    asyncio.run(run_test())


class _async_iter:
    """Tiny async iterator wrapper for lists."""

    def __init__(self, items):
        self._items = items

    def __aiter__(self):
        self._index = 0
        return self

    async def __anext__(self):
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item
