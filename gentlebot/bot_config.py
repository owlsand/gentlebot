"""
Source of truth for IDs & tokens (DEPRECATED - use gentlebot.config.settings instead)
======================================================
This module is maintained for backward compatibility.
New code should import from gentlebot.config.settings.

Supports **multi‑env** (TEST vs PROD) so you can run the bot in your sandbox
Guild first, then flip the ENV var when you deploy.

Usage
-----
$ export env=TEST  # or PROD (default PROD)
$ python -m gentlebot

* .env (git‑ignored) keeps only TOKEN values*
DISCORD_TOKEN=xxx
"""
from __future__ import annotations

import logging

# Import the new centralized settings
from .config.settings import settings

log = logging.getLogger(__name__)

# ─── Backward Compatibility Exports ───────────────────────────────────────
# These exports maintain compatibility with existing code that imports from bot_config

# Environment
env = settings.env
IS_TEST = settings.is_test

# Tokens and API Keys
TOKEN = settings.discord.token
ALPHA_VANTAGE_KEY = settings.api_keys.alpha_vantage_key
YAHOO_CLIENT_ID = settings.api_keys.yahoo_client_id
YAHOO_CLIENT_SECRET = settings.api_keys.yahoo_client_secret
YAHOO_REFRESH_TOKEN = settings.api_keys.yahoo_refresh_token
YAHOO_LEAGUE_KEY = settings.api_keys.yahoo_league_key

# Discord Guild and Channels
GUILD_ID = settings.discord.guild_id
FINANCE_CHANNEL_ID = settings.discord.finance_channel_id
MARKET_CHANNEL_ID = settings.discord.market_channel_id
F1_DISCORD_CHANNEL_ID = settings.discord.f1_channel_id
SPORTS_CHANNEL_ID = settings.discord.sports_channel_id
FANTASY_CHANNEL_ID = settings.discord.fantasy_channel_id
DAILY_PING_CHANNEL = settings.discord.daily_ping_channel
MONEY_TALK_CHANNEL = settings.discord.money_talk_channel
LOBBY_CHANNEL_ID = settings.discord.lobby_channel_id

# Roles - Engagement badges
ROLE_GHOST = settings.discord.role_ghost
ROLE_TOP_POSTER = settings.discord.role_top_poster
ROLE_CERTIFIED_BANGER = settings.discord.role_certified_banger
ROLE_TOP_CURATOR = settings.discord.role_top_curator
ROLE_EARLY_BIRD = settings.discord.role_early_bird
ROLE_SUMMONER = settings.discord.role_summoner
ROLE_LORE_CREATOR = settings.discord.role_lore_creator
ROLE_REACTION_ENGINEER = settings.discord.role_reaction_engineer
ROLE_GALAXY_BRAIN = settings.discord.role_galaxy_brain
ROLE_WORDSMITH = settings.discord.role_wordsmith
ROLE_SNIPER = settings.discord.role_sniper
ROLE_NIGHT_OWL = settings.discord.role_night_owl
ROLE_COMEBACK_KID = settings.discord.role_comeback_kid
ROLE_GHOSTBUSTER = settings.discord.role_ghostbuster
ROLE_DAILY_HERO = settings.discord.role_daily_hero

# Roles - Inactivity flags
ROLE_SHADOW_FLAG = settings.discord.role_shadow_flag
ROLE_LURKER_FLAG = settings.discord.role_lurker_flag
ROLE_NPC_FLAG = settings.discord.role_npc_flag

# Tiered badges configuration
TIERED_BADGES = settings.discord.tiered_badges or {}

# Feature flags
INACTIVE_DAYS = settings.features.inactive_days
DAILY_PROMPT_ENABLED = settings.features.daily_prompt_enabled

# Helper properties
AUTO_ROLE_IDS = settings.auto_role_ids
ROLE_DESCRIPTIONS = settings.role_descriptions

# Log configuration loaded
log.info("Loaded %s env for Guild %s (via settings)", env, GUILD_ID)
