"""
Centralized configuration with validation for Gentlebot.

This module provides a Settings class that:
- Validates required environment variables on startup
- Provides type hints for better IDE support
- Centralizes all configuration in one place
- Supports multi-environment (TEST vs PROD)
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

log = logging.getLogger(__name__)


def _int_env(var: str, default: int = 0) -> int:
    """Return int value from ENV or default if unset or invalid."""
    value = os.getenv(var)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        log.warning("Invalid integer for %s: %s; using %s", var, value, default)
        return default


def _bool_env(var: str, default: bool = False) -> bool:
    """Return boolean value from ENV or default if unset or invalid."""
    value = os.getenv(var)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    log.warning("Invalid boolean for %s: %s; using %s", var, value, default)
    return default


@dataclass
class DatabaseConfig:
    """Database configuration."""

    dsn: Optional[str] = None

    def __post_init__(self):
        """Build database URL from environment variables."""
        self.dsn = os.getenv("PG_DSN") or os.getenv("DATABASE_URL")
        if not self.dsn:
            user = os.getenv("PG_USER")
            pwd = os.getenv("PG_PASSWORD")
            db = os.getenv("PG_DB")
            if user and pwd and db:
                self.dsn = f"postgresql+asyncpg://{user}:{pwd}@db:5432/{db}"


@dataclass
class DiscordConfig:
    """Discord-specific configuration."""

    token: str
    guild_id: int

    # Channels
    finance_channel_id: int
    market_channel_id: int
    f1_channel_id: int
    sports_channel_id: int
    fantasy_channel_id: int
    daily_ping_channel: int
    money_talk_channel: int
    lobby_channel_id: int = 0

    # Roles - Engagement badges
    role_ghost: int = 0
    role_top_poster: int = 0
    role_certified_banger: int = 0
    role_top_curator: int = 0
    role_early_bird: int = 0
    role_summoner: int = 0
    role_lore_creator: int = 0
    role_reaction_engineer: int = 0
    role_galaxy_brain: int = 0
    role_wordsmith: int = 0
    role_sniper: int = 0
    role_night_owl: int = 0
    role_comeback_kid: int = 0
    role_ghostbuster: int = 0
    role_daily_hero: int = 0

    # Roles - Inactivity flags
    role_shadow_flag: int = 0
    role_lurker_flag: int = 0
    role_npc_flag: int = 0

    # Tiered badges configuration
    tiered_badges: dict = None

    def __post_init__(self):
        """Validate Discord configuration."""
        if not self.token:
            raise ValueError("DISCORD_TOKEN is required")
        if not self.guild_id:
            raise ValueError("Guild ID is required")


@dataclass
class APIKeysConfig:
    """External API keys configuration."""

    alpha_vantage_key: Optional[str] = None
    yahoo_client_id: Optional[str] = None
    yahoo_client_secret: Optional[str] = None
    yahoo_refresh_token: Optional[str] = None
    yahoo_league_key: Optional[str] = None
    gemini_api_key: Optional[str] = None


@dataclass
class FeaturesConfig:
    """Feature flags and settings."""

    inactive_days: int = 14
    daily_prompt_enabled: bool = False


class Settings:
    """
    Centralized settings for Gentlebot.

    This class loads and validates all configuration on initialization.
    Access configuration through the global `settings` instance.
    """

    def __init__(self):
        """Initialize settings and validate required configuration."""
        self.env = os.getenv("env", "prod").upper()
        self.is_test = self.env == "TEST"
        self.is_prod = not self.is_test

        # Initialize configuration sections
        self.database = DatabaseConfig()
        self.api_keys = self._load_api_keys()
        self.features = self._load_features()
        self.discord = self._load_discord_config()

        # Validate required configuration
        self._validate()

        log.info("Loaded %s environment for Guild %s", self.env, self.discord.guild_id)

    def _load_api_keys(self) -> APIKeysConfig:
        """Load API keys from environment."""
        return APIKeysConfig(
            alpha_vantage_key=os.getenv("ALPHA_VANTAGE_KEY"),
            yahoo_client_id=os.getenv("YAHOO_CLIENT_ID"),
            yahoo_client_secret=os.getenv("YAHOO_CLIENT_SECRET"),
            yahoo_refresh_token=os.getenv("YAHOO_REFRESH_TOKEN"),
            yahoo_league_key=os.getenv("YAHOO_LEAGUE_KEY"),
            gemini_api_key=os.getenv("GEMINI_API_KEY"),
        )

    def _load_features(self) -> FeaturesConfig:
        """Load feature flags from environment."""
        return FeaturesConfig(
            inactive_days=_int_env("INACTIVE_DAYS", 14),
            daily_prompt_enabled=_bool_env("DAILY_PROMPT_ENABLED", False),
        )

    def _load_discord_config(self) -> DiscordConfig:
        """Load Discord configuration based on environment."""
        token = os.getenv("DISCORD_TOKEN")
        if not token:
            raise ValueError(
                "DISCORD_TOKEN environment variable is required. "
                "Set it in your .env file or environment."
            )

        if self.is_test:
            return self._load_test_discord_config(token)
        else:
            return self._load_prod_discord_config(token)

    def _load_test_discord_config(self, token: str) -> DiscordConfig:
        """Load TEST environment Discord configuration."""
        tiered_badges = {}  # TEST doesn't use tiered badges

        return DiscordConfig(
            token=token,
            guild_id=1135418490979893318,
            finance_channel_id=1135418490979893321,
            market_channel_id=_int_env("MARKET_CHANNEL_ID", 0),
            f1_channel_id=1135418490979893321,
            sports_channel_id=_int_env("SPORTS_CHANNEL_ID", 1135418490979893321),
            fantasy_channel_id=_int_env("FANTASY_CHANNEL_ID", _int_env("SPORTS_CHANNEL_ID", 1135418490979893321)),
            daily_ping_channel=1374238199676928070,
            money_talk_channel=_int_env("MONEY_TALK_CHANNEL", 1374238246468456469),
            lobby_channel_id=0,
            role_ghost=1374598613514063942,
            role_top_poster=_int_env("ROLE_TOP_POSTER", 0),
            role_certified_banger=_int_env("ROLE_CERTIFIED_BANGER", 0),
            role_top_curator=_int_env("ROLE_TOP_CURATOR", 0),
            role_early_bird=_int_env("ROLE_EARLY_BIRD", 0),
            role_summoner=_int_env("ROLE_SUMMONER", 0),
            role_lore_creator=_int_env("ROLE_LORE_CREATOR", 0),
            role_reaction_engineer=_int_env("ROLE_REACTION_ENGINEER", 0),
            role_galaxy_brain=_int_env("ROLE_GALAXY_BRAIN", 0),
            role_wordsmith=_int_env("ROLE_WORDSMITH", 0),
            role_sniper=_int_env("ROLE_SNIPER", 0),
            role_night_owl=_int_env("ROLE_NIGHT_OWL", 0),
            role_comeback_kid=_int_env("ROLE_COMEBACK_KID", 0),
            role_ghostbuster=_int_env("ROLE_GHOSTBUSTER", 0),
            role_shadow_flag=_int_env("ROLE_SHADOW_FLAG", 0),
            role_lurker_flag=_int_env("ROLE_LURKER_FLAG", 0),
            role_npc_flag=_int_env("ROLE_NPC_FLAG", 0),
            role_daily_hero=0,
            tiered_badges=tiered_badges,
        )

    def _load_prod_discord_config(self, token: str) -> DiscordConfig:
        """Load PROD environment Discord configuration."""
        tiered_badges = {
            'top_poster': {
                'metric': 'msgs',
                'threshold': 10,
                'roles': {
                    'gold': 1391637786406289508,
                    'silver': 1397431514043781170,
                    'bronze': 1397432033113800877,
                },
            },
            'reaction_magnet': {
                'metric': 'reacts',
                'threshold': 10,
                'roles': {
                    'gold': 1391637939900907661,
                    'silver': 1397432612364095589,
                    'bronze': 1397432799795085372,
                },
            },
        }

        return DiscordConfig(
            token=token,
            guild_id=973284857885126746,
            finance_channel_id=1160414402076491878,
            market_channel_id=_int_env("MARKET_CHANNEL_ID", 0),
            f1_channel_id=1121104901175509106,
            sports_channel_id=_int_env("SPORTS_CHANNEL_ID", 1121104901175509106),
            fantasy_channel_id=_int_env("FANTASY_CHANNEL_ID", 1399587080258064447),
            daily_ping_channel=1136095810510143518,
            money_talk_channel=_int_env("MONEY_TALK_CHANNEL", 1160414402076491878),
            lobby_channel_id=_int_env("LOBBY_CHANNEL_ID", 973284857885126749),
            role_ghost=1373545254497816626,
            role_top_poster=_int_env("ROLE_TOP_POSTER", 1391637786406289508),
            role_certified_banger=_int_env("ROLE_CERTIFIED_BANGER", 1391637939900907661),
            role_top_curator=_int_env("ROLE_TOP_CURATOR", 1391638247570149400),
            role_early_bird=_int_env("ROLE_EARLY_BIRD", 1391638519667228672),
            role_summoner=_int_env("ROLE_SUMMONER", 1391638673405116446),
            role_lore_creator=_int_env("ROLE_LORE_CREATOR", 1391976400193327124),
            role_reaction_engineer=_int_env("ROLE_REACTION_ENGINEER", 1391976121758908548),
            role_galaxy_brain=_int_env("ROLE_GALAXY_BRAIN", 1392716380997943356),
            role_wordsmith=_int_env("ROLE_WORDSMITH", 1392716612410544299),
            role_sniper=_int_env("ROLE_SNIPER", 1392716717255557150),
            role_night_owl=_int_env("ROLE_NIGHT_OWL", 1392716859161448478),
            role_comeback_kid=_int_env("ROLE_COMEBACK_KID", 1392716982582902905),
            role_ghostbuster=_int_env("ROLE_GHOSTBUSTER", 1392717092658352289),
            role_shadow_flag=_int_env("ROLE_SHADOW_FLAG", 1391977459850809425),
            role_lurker_flag=_int_env("ROLE_LURKER_FLAG", 1391978324510642258),
            role_npc_flag=_int_env("ROLE_NPC_FLAG", 1391978703566934087),
            role_daily_hero=_int_env("ROLE_DAILY_HERO", 1397079979547955242),
            tiered_badges=tiered_badges,
        )

    def _validate(self):
        """Validate that all required configuration is present."""
        errors = []

        if not self.discord.token:
            errors.append("DISCORD_TOKEN is required")

        if not self.database.dsn:
            errors.append(
                "Database configuration is incomplete. Set PG_DSN or "
                "(PG_USER, PG_PASSWORD, PG_DB) environment variables."
            )

        if errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            raise ValueError(error_msg)

    @property
    def auto_role_ids(self) -> set[int]:
        """Get set of all automatically assigned role IDs."""
        return {
            self.discord.role_ghost,
            self.discord.role_top_poster,
            self.discord.role_certified_banger,
            self.discord.role_top_curator,
            self.discord.role_early_bird,
            self.discord.role_summoner,
            self.discord.role_lore_creator,
            self.discord.role_reaction_engineer,
            self.discord.role_galaxy_brain,
            self.discord.role_wordsmith,
            self.discord.role_sniper,
            self.discord.role_night_owl,
            self.discord.role_comeback_kid,
            self.discord.role_ghostbuster,
            self.discord.role_shadow_flag,
            self.discord.role_lurker_flag,
            self.discord.role_npc_flag,
        } - {0}  # Remove any unset roles (0 values)

    @property
    def role_descriptions(self) -> dict[int, str]:
        """Get descriptive text for automatically assigned roles."""
        return {
            self.discord.role_top_poster: "Most messages in the last 14 days",
            self.discord.role_certified_banger: "Highest laugh reaction ratio (min 10 msgs) in the last 14 days",
            self.discord.role_top_curator: "Shared the most popular rich posts in the last 14 days",
            self.discord.role_early_bird: "Most messages between 5am and 8:30am PT in the last 14 days",
            self.discord.role_summoner: "Most mentions of others in the last 30 days",
            self.discord.role_lore_creator: "Most replied-to user in the last 30 days",
            self.discord.role_reaction_engineer: "Created emojis used most as reactions in the last 30 days",
            self.discord.role_galaxy_brain: "Longest single message in the last 5 days",
            self.discord.role_wordsmith: "Highest average words per message (min 3) in the last 5 days",
            self.discord.role_sniper: "Best reactions-per-word ratio in the last 5 days",
            self.discord.role_night_owl: "Most messages between 10pm and 4am PT in the last 14 days",
            self.discord.role_comeback_kid: "Most mentioned user in the last 14 days",
            self.discord.role_ghostbuster: "Broke a chat lull exceeding 24 hours",
            self.discord.role_ghost: "No messages or reactions in the last 14 days",
            self.discord.role_shadow_flag: "No messages in 14 days but mentioned or reacted to in 30 days",
            self.discord.role_lurker_flag: "1–5 messages or up to 15 reactions in the last 14 days",
            self.discord.role_npc_flag: "Active without long or rich posts in the last 30 days",
        }


# Global settings instance
settings = Settings()
