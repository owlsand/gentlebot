import asyncio
import datetime as dt
from types import SimpleNamespace

import gentlebot.cogs.lurker_ping_cog as module
from gentlebot.cogs.lurker_ping_cog import LurkerPingCog


class DummyTextChannel:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send(self, message: str) -> None:
        self.sent.append(message)


class FakePool:
    def __init__(
        self,
        last_message_at: dt.datetime,
        statuses_after: list[tuple[str, dt.datetime]],
        status_before: str | None = None,
    ) -> None:
        self.last_message_at = last_message_at
        self.statuses_after = statuses_after
        self.status_before = status_before

    async def fetchrow(self, query: str, *args):
        if "MAX(created_at)" in query:
            return {"last_message_at": self.last_message_at}
        if "event_at <= $3" in query:
            if self.status_before is None:
                return None
            return {"status": self.status_before}
        return None

    async def fetch(self, query: str, *args):
        if "event_at > $3" in query:
            return [
                {"status": status, "event_at": ts}
                for status, ts in self.statuses_after
            ]
        return []


def test_lurker_ping_triggers(monkeypatch):
    now = dt.datetime(2024, 5, 15, tzinfo=dt.timezone.utc)
    last_message = now - dt.timedelta(days=8)
    statuses = [
        ("offline", last_message + dt.timedelta(days=1)),
        ("online", last_message + dt.timedelta(days=1, minutes=5)),
        ("offline", last_message + dt.timedelta(days=4)),
        ("online", last_message + dt.timedelta(days=4, minutes=3)),
    ]

    pool = FakePool(last_message, statuses, status_before="offline")
    cog = LurkerPingCog(SimpleNamespace())
    cog.pool = pool  # type: ignore[assignment]
    cog._last_ping.clear()

    monkeypatch.setattr(module.cfg, "GUILD_ID", 1, raising=False)
    monkeypatch.setattr(module.cfg, "LOBBY_CHANNEL_ID", 2, raising=False)

    dummy_base = type("DummyBase", (), {})
    monkeypatch.setattr(module.discord, "TextChannel", dummy_base)
    channel = type("DummyChannel", (dummy_base, DummyTextChannel), {} )()

    bot_user = SimpleNamespace(id=999)
    cog.bot = SimpleNamespace(get_channel=lambda _: channel, user=bot_user)  # type: ignore[assignment]

    monkeypatch.setattr(module.discord.utils, "utcnow", lambda: now)

    captured: list[tuple[str, list[dict], float]] = []

    def fake_generate(route, messages, temperature, *args, **kwargs):
        captured.append((route, messages, temperature))
        return "Hello <MENTION> we see you lurking! Why so quiet?"

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(module.router, "generate", fake_generate)
    monkeypatch.setattr(module.asyncio, "to_thread", fake_to_thread)

    before = SimpleNamespace(raw_status="offline")
    after = SimpleNamespace(
        raw_status="online",
        guild=SimpleNamespace(id=1),
        bot=False,
        id=42,
        mention="@Tester",
        display_name="Tester",
    )

    async def run() -> None:
        await cog.on_presence_update(before, after)

    asyncio.run(run())

    assert channel.sent == ["Hello @Tester we see you lurking! Why so quiet?"]
    assert captured and captured[0][0] == "scheduled"
    assert captured[0][2] == cog.temperature


def test_lurker_ping_skips_without_two_logins(monkeypatch):
    now = dt.datetime(2024, 5, 15, tzinfo=dt.timezone.utc)
    last_message = now - dt.timedelta(days=8)
    statuses = [
        ("offline", last_message + dt.timedelta(days=1)),
        ("online", last_message + dt.timedelta(days=1, minutes=5)),
    ]

    pool = FakePool(last_message, statuses, status_before="offline")
    cog = LurkerPingCog(SimpleNamespace())
    cog.pool = pool  # type: ignore[assignment]

    monkeypatch.setattr(module.cfg, "GUILD_ID", 1, raising=False)
    monkeypatch.setattr(module.cfg, "LOBBY_CHANNEL_ID", 2, raising=False)
    dummy_base = type("DummyBase", (), {})
    monkeypatch.setattr(module.discord, "TextChannel", dummy_base)
    channel = type("DummyChannel", (dummy_base, DummyTextChannel), {} )()

    cog.bot = SimpleNamespace(get_channel=lambda _: channel, user=SimpleNamespace(id=999))  # type: ignore[assignment]

    monkeypatch.setattr(module.discord.utils, "utcnow", lambda: now)

    called = False

    def fake_generate(*args, **kwargs):
        nonlocal called
        called = True
        return "<MENTION>"

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(module.router, "generate", fake_generate)
    monkeypatch.setattr(module.asyncio, "to_thread", fake_to_thread)

    before = SimpleNamespace(raw_status="offline")
    after = SimpleNamespace(
        raw_status="online",
        guild=SimpleNamespace(id=1),
        bot=False,
        id=42,
        mention="@Tester",
        display_name="Tester",
    )

    async def run() -> None:
        await cog.on_presence_update(before, after)

    asyncio.run(run())

    assert channel.sent == []
    assert not called


def test_lurker_ping_skips_when_recent_message(monkeypatch):
    now = dt.datetime(2024, 5, 15, tzinfo=dt.timezone.utc)
    last_message = now - dt.timedelta(days=2)

    pool = FakePool(last_message, [], status_before="offline")
    cog = LurkerPingCog(SimpleNamespace())
    cog.pool = pool  # type: ignore[assignment]

    monkeypatch.setattr(module.cfg, "GUILD_ID", 1, raising=False)
    monkeypatch.setattr(module.cfg, "LOBBY_CHANNEL_ID", 2, raising=False)
    dummy_base = type("DummyBase", (), {})
    monkeypatch.setattr(module.discord, "TextChannel", dummy_base)
    channel = type("DummyChannel", (dummy_base, DummyTextChannel), {} )()

    cog.bot = SimpleNamespace(get_channel=lambda _: channel, user=SimpleNamespace(id=999))  # type: ignore[assignment]
    monkeypatch.setattr(module.discord.utils, "utcnow", lambda: now)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(module.asyncio, "to_thread", fake_to_thread)

    triggered = False

    def fake_generate(*args, **kwargs):
        nonlocal triggered
        triggered = True
        return "<MENTION>"

    monkeypatch.setattr(module.router, "generate", fake_generate)

    before = SimpleNamespace(raw_status="offline")
    after = SimpleNamespace(
        raw_status="online",
        guild=SimpleNamespace(id=1),
        bot=False,
        id=42,
        mention="@Tester",
        display_name="Tester",
    )

    async def run() -> None:
        await cog.on_presence_update(before, after)

    asyncio.run(run())

    assert channel.sent == []
    assert not triggered
