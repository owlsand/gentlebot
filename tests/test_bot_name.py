"""The bot's name lives in one variable: bot_config.BOT_NAME.

Regression guard for the identity crisis where prompts hardcoded
"You are Gentlebot" while the bot's Discord username is Clanker, so the
bot insisted it was Gentlebot-not-Clanker and disowned its own messages
(chat history attributes them to the Discord username).

Every LLM prompt / system instruction must interpolate cfg.BOT_NAME
instead of hardcoding a name. Renaming the bot must be a one-place
change.
"""
from pathlib import Path

from gentlebot import bot_config as cfg
from gentlebot.capabilities import CapabilityRegistry, get_default_capabilities
from gentlebot.llm.router import SYSTEM_INSTRUCTION

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "gentlebot"

# Identity phrasings that must never be hardcoded with the old name.
FORBIDDEN = [
    "You are Gentlebot",
    "Sign as 'Gentlebot'",
    "@Gentlebot followed",
    "From Gentlebot",
    "Ask Gentlebot",
    "Gentlebot version:",
    "Gentlebot has lots of hidden talents",
]


def test_bot_name_defaults_to_discord_username():
    # The bot's Discord username (id 1358958872739447018) is Clanker.
    assert cfg.BOT_NAME == "Clanker"


def test_system_instruction_uses_bot_name():
    assert SYSTEM_INSTRUCTION.startswith(f"You are {cfg.BOT_NAME},")
    assert f"messages authored by {cfg.BOT_NAME} are your own" in SYSTEM_INSTRUCTION


def test_default_capabilities_use_bot_name():
    prompt = get_default_capabilities()
    assert f"You are {cfg.BOT_NAME}," in prompt


def test_capability_registry_prompt_uses_bot_name():
    registry = CapabilityRegistry.__new__(CapabilityRegistry)
    registry._commands = []
    registry._reactions = []
    registry._scheduled = []
    prompt = registry.generate_prompt()
    assert f"You are {cfg.BOT_NAME}," in prompt
    assert f"@{cfg.BOT_NAME} followed by a question" in prompt


def test_no_hardcoded_identity_prompts_remain():
    offenders = []
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for phrase in FORBIDDEN:
            if phrase in text:
                offenders.append(f"{path.relative_to(PACKAGE_DIR)}: {phrase!r}")
    assert offenders == [], "Hardcoded bot identity found:\n" + "\n".join(offenders)
