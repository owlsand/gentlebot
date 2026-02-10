"""Tests for the Welcome Back cog."""
import asyncio
import types
from datetime import timedelta


def test_welcome_templates_not_empty():
    """WELCOME_TEMPLATES should have at least one entry."""
    from gentlebot.cogs.welcome_back_cog import WELCOME_TEMPLATES

    assert len(WELCOME_TEMPLATES) >= 1
    for t in WELCOME_TEMPLATES:
        assert "{name}" in t


def test_welcome_templates_format():
    """All templates should format correctly with a name."""
    from gentlebot.cogs.welcome_back_cog import WELCOME_TEMPLATES

    for t in WELCOME_TEMPLATES:
        result = t.format(name="TestUser")
        assert "TestUser" in result


def test_capabilities_registered():
    """WelcomeBackCog should have CAPABILITIES with command and scheduled."""
    from gentlebot.cogs.welcome_back_cog import WelcomeBackCog
    from gentlebot.capabilities import CogCapabilities

    assert hasattr(WelcomeBackCog, "CAPABILITIES")
    assert isinstance(WelcomeBackCog.CAPABILITIES, CogCapabilities)
    assert len(WelcomeBackCog.CAPABILITIES.commands) == 1
    assert WelcomeBackCog.CAPABILITIES.commands[0].name == "recap"
    assert len(WelcomeBackCog.CAPABILITIES.scheduled) == 1


def test_inactivity_roles_detection():
    """_get_inactivity_roles should return a non-empty set in prod."""
    from gentlebot.cogs.welcome_back_cog import _get_inactivity_roles

    roles = _get_inactivity_roles()
    # Should have at least one role ID (ROLE_GHOST is always set)
    assert isinstance(roles, set)
    assert len(roles) >= 1


def test_on_message_skips_bot():
    """on_message should skip bot messages."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.welcome_back_cog import WelcomeBackCog

        cog = WelcomeBackCog(bot)
        cog.pool = types.SimpleNamespace()

        msg = types.SimpleNamespace(
            id=456,
            author=types.SimpleNamespace(bot=True),
            guild=types.SimpleNamespace(id=999),
            content="hello",
        )

        await cog.on_message(msg)

    asyncio.run(run())


def test_on_message_skips_dm():
    """on_message should skip DMs (guild=None)."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.welcome_back_cog import WelcomeBackCog

        cog = WelcomeBackCog(bot)
        cog.pool = types.SimpleNamespace()

        msg = types.SimpleNamespace(
            id=456,
            author=types.SimpleNamespace(bot=False),
            guild=None,
            content="hello",
        )

        await cog.on_message(msg)

    asyncio.run(run())


def test_on_message_skips_non_member():
    """on_message should skip if author is not a Member (no roles)."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs import welcome_back_cog
        from gentlebot.cogs.welcome_back_cog import WelcomeBackCog
        import gentlebot.bot_config as cfg

        cog = WelcomeBackCog(bot)
        cog.pool = types.SimpleNamespace()

        # SimpleNamespace isn't a discord.Member, so isinstance check fails
        msg = types.SimpleNamespace(
            id=456,
            author=types.SimpleNamespace(
                bot=False,
                roles=[],
                id=789,
                display_name="Test",
            ),
            guild=types.SimpleNamespace(id=cfg.GUILD_ID),
            content="hello",
        )

        await cog.on_message(msg)

    asyncio.run(run())


def test_on_message_skips_wrong_guild():
    """on_message should skip messages from other guilds."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.welcome_back_cog import WelcomeBackCog

        cog = WelcomeBackCog(bot)
        cog.pool = types.SimpleNamespace()

        msg = types.SimpleNamespace(
            id=456,
            author=types.SimpleNamespace(bot=False),
            guild=types.SimpleNamespace(id=99999),  # Wrong guild
            content="hello",
        )

        await cog.on_message(msg)

    asyncio.run(run())


def test_build_recap_embed_empty_stats():
    """_build_recap_embed should handle zero-stat users gracefully."""
    async def run():
        bot = types.SimpleNamespace()
        bot.user = types.SimpleNamespace(id=123)

        from gentlebot.cogs.welcome_back_cog import WelcomeBackCog

        cog = WelcomeBackCog(bot)

        # Mock pool that returns 0/empty for all queries
        async def fetchval(*args, **kwargs):
            return 0

        async def fetch(*args, **kwargs):
            return []

        async def fetchrow(*args, **kwargs):
            return None

        cog.pool = types.SimpleNamespace(
            fetchval=fetchval,
            fetch=fetch,
            fetchrow=fetchrow,
        )

        member = types.SimpleNamespace(
            id=789,
            display_name="TestUser",
            guild=types.SimpleNamespace(name="TestGuild"),
        )

        embed = await cog._build_recap_embed(member, timedelta(days=30))
        assert embed.title == "📊 Your Monthly Recap"
        assert "TestGuild" in embed.description

    asyncio.run(run())


def test_config_defaults():
    """Config defaults should be sensible."""
    import gentlebot.bot_config as cfg

    assert cfg.WELCOME_BACK_ENABLED is True
    assert cfg.WELCOME_BACK_MIN_GAP_DAYS == 7
    assert cfg.WELCOME_BACK_COOLDOWN_DAYS == 30
    assert cfg.MONTHLY_RECAP_DM_ENABLED is True
    assert cfg.FEATURE_DISCOVERY_ENABLED is True
    assert cfg.FEATURE_SPOTLIGHT_INTERVAL_DAYS == 5
