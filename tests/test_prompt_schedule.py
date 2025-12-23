from datetime import datetime, timedelta
import asyncio
import types
from gentlebot.cogs import prompt_cog


def test_next_run_time_before_schedule():
    tz = prompt_cog.LOCAL_TZ
    now = datetime(2023, 1, 1, 10, 0, tzinfo=tz)
    next_run = prompt_cog.PromptCog(None)._next_run_time(now)
    assert next_run.date() == now.date()
    assert next_run.hour == prompt_cog.SCHEDULE_HOUR
    assert next_run.minute == prompt_cog.SCHEDULE_MINUTE


def test_next_run_time_after_schedule():
    tz = prompt_cog.LOCAL_TZ
    now = datetime(2023, 1, 1, 13, 0, tzinfo=tz)
    next_run = prompt_cog.PromptCog(None)._next_run_time(now)
    assert next_run.date() == now.date() + timedelta(days=1)
    assert next_run.hour == prompt_cog.SCHEDULE_HOUR
    assert next_run.minute == prompt_cog.SCHEDULE_MINUTE


def test_scheduler_restarts_when_done(monkeypatch):
    """Scheduler should restart if previous task finished or crashed."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    monkeypatch.setattr(prompt_cog.cfg, "DAILY_PROMPT_ENABLED", True)

    async def dummy_wait():
        pass

    bot = types.SimpleNamespace(
        loop=loop,
        wait_until_ready=dummy_wait,
        is_closed=lambda: False,
    )
    cog = prompt_cog.PromptCog(bot)

    async def fake_scheduler(self):
        return

    monkeypatch.setattr(prompt_cog.PromptCog, "_scheduler", fake_scheduler)

    async def run():
        await cog.on_ready()
        first = cog._scheduler_task
        assert first is not None
        await asyncio.sleep(0)
        assert first.done()
        await cog.on_ready()
        second = cog._scheduler_task
        assert second is not first

    try:
        loop.run_until_complete(run())
    finally:
        asyncio.set_event_loop(None)
        loop.close()


def test_scheduler_pauses_when_disabled(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    monkeypatch.setattr(prompt_cog.cfg, "DAILY_PROMPT_ENABLED", False)

    async def dummy_wait():
        pass

    bot = types.SimpleNamespace(
        loop=loop,
        wait_until_ready=dummy_wait,
        is_closed=lambda: False,
    )
    cog = prompt_cog.PromptCog(bot)

    async def run():
        await cog.on_ready()
        assert cog._scheduler_task is None

    try:
        loop.run_until_complete(run())
    finally:
        asyncio.set_event_loop(None)
        loop.close()
