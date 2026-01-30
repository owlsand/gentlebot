"""
Source of truth for IDs & tokens
======================================================
Supports **multi‑env** (TEST vs PROD) so you can run the bot in your sandbox
Guild first, then flip the ENV var when you deploy.

Usage
-----
$ export BOT_ENV=TEST  # or PROD (default PROD)
$ python -m gentlebot

* .env (git‑ignored) keeps only TOKEN values*
DISCORD_TOKEN_TEST=xxx
DISCORD_TOKEN_PROD=yyy

You can also inject IDs via env‑vars if you’d rather not commit them.
"""
from __future__ import annotations
import os
import logging
from .util import bool_env, int_env
from dotenv import load_dotenv
load_dotenv()

# ─── Select env ────────────────────────────────────────────────────────────
env = os.getenv("env", "prod").upper()
IS_TEST = env == "TEST"

# ─── Tokens ───────────────────────────────────────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN")
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY")
YAHOO_CLIENT_ID = os.getenv("YAHOO_CLIENT_ID")
YAHOO_CLIENT_SECRET = os.getenv("YAHOO_CLIENT_SECRET")
YAHOO_REFRESH_TOKEN = os.getenv("YAHOO_REFRESH_TOKEN")
YAHOO_LEAGUE_KEY = os.getenv("YAHOO_LEAGUE_KEY")

# ─── IDs per environment ──────────────────────────────────────────────────
if IS_TEST:
    # -------- TEST SERVER IDs --------
    GUILD_ID = 1135418490979893318

    # -------- CHANNELS --------
    FINANCE_CHANNEL_ID=1135418490979893321 #test channel for market_bot.py
    MARKET_CHANNEL_ID = int_env("MARKET_CHANNEL_ID", 0)
    F1_DISCORD_CHANNEL_ID = 1135418490979893321 #test channel for f1_bot.py
    SPORTS_CHANNEL_ID = int_env("SPORTS_CHANNEL_ID", 1135418490979893321)
    FANTASY_CHANNEL_ID = int_env("FANTASY_CHANNEL_ID", SPORTS_CHANNEL_ID)
    DAILY_PING_CHANNEL = 1374238199676928070
    MONEY_TALK_CHANNEL = int_env("MONEY_TALK_CHANNEL", 1374238246468456469)
    LOBBY_CHANNEL_ID = int_env("LOBBY_CHANNEL_ID", 1135418490979893321)
    WINS_CHANNEL_ID = int_env("WINS_CHANNEL_ID", 1465222564514103358)  # #wins channel for celebrations

    # -------- ROLES --------
    ROLE_GHOST = 1374598613514063942
    # ----- engagement badges (env vars)
    ROLE_TOP_POSTER = int_env("ROLE_TOP_POSTER", 0)
    ROLE_CERTIFIED_BANGER = int_env("ROLE_CERTIFIED_BANGER", 0)
    ROLE_TOP_CURATOR = int_env("ROLE_TOP_CURATOR", 0)
    ROLE_EARLY_BIRD = int_env("ROLE_EARLY_BIRD", 0)
    ROLE_SUMMONER = int_env("ROLE_SUMMONER", 0)
    ROLE_LORE_CREATOR = int_env("ROLE_LORE_CREATOR", 0)
    ROLE_REACTION_ENGINEER = int_env("ROLE_REACTION_ENGINEER", 0)
    ROLE_GALAXY_BRAIN = int_env("ROLE_GALAXY_BRAIN", 0)
    ROLE_WORDSMITH = int_env("ROLE_WORDSMITH", 0)
    ROLE_SNIPER = int_env("ROLE_SNIPER", 0)
    ROLE_NIGHT_OWL = int_env("ROLE_NIGHT_OWL", 0)
    ROLE_COMEBACK_KID = int_env("ROLE_COMEBACK_KID", 0)
    ROLE_GHOSTBUSTER = int_env("ROLE_GHOSTBUSTER", 0)
    # ----- inactivity flags (env vars)
    ROLE_SHADOW_FLAG = int_env("ROLE_SHADOW_FLAG", 0)
    ROLE_LURKER_FLAG = int_env("ROLE_LURKER_FLAG", 0)
    ROLE_NPC_FLAG = int_env("ROLE_NPC_FLAG", 0)

else:
    # -------- PROD SERVER IDs --------
    GUILD_ID=973284857885126746

    # -------- CHANNELS --------
    FINANCE_CHANNEL_ID=1160414402076491878
    MARKET_CHANNEL_ID = int_env("MARKET_CHANNEL_ID", 0)
    F1_DISCORD_CHANNEL_ID=1121104901175509106
    SPORTS_CHANNEL_ID = int_env("SPORTS_CHANNEL_ID", 1121104901175509106)
    FANTASY_CHANNEL_ID = int_env("FANTASY_CHANNEL_ID", 1399587080258064447)
    DAILY_PING_CHANNEL = 1136095810510143518
    MONEY_TALK_CHANNEL = int_env("MONEY_TALK_CHANNEL", 1160414402076491878)
    LOBBY_CHANNEL_ID = int_env("LOBBY_CHANNEL_ID", 973284857885126749)
    WINS_CHANNEL_ID = int_env("WINS_CHANNEL_ID", 0)  # #wins channel for celebrations


    # -------- ROLES --------
    ROLE_GHOST = 1373545254497816626
    # ----- engagement badges (env vars)
    ROLE_TOP_POSTER = int_env("ROLE_TOP_POSTER", 1391637786406289508)
    ROLE_CERTIFIED_BANGER = int_env("ROLE_CERTIFIED_BANGER", 1391637939900907661)
    ROLE_TOP_CURATOR = int_env("ROLE_TOP_CURATOR", 1391638247570149400)
    ROLE_EARLY_BIRD = int_env("ROLE_EARLY_BIRD", 1391638519667228672)
    ROLE_SUMMONER = int_env("ROLE_SUMMONER", 1391638673405116446)
    ROLE_LORE_CREATOR = int_env("ROLE_LORE_CREATOR", 1391976400193327124)
    ROLE_REACTION_ENGINEER = int_env("ROLE_REACTION_ENGINEER", 1391976121758908548)
    ROLE_GALAXY_BRAIN = int_env("ROLE_GALAXY_BRAIN", 1392716380997943356)
    ROLE_WORDSMITH = int_env("ROLE_WORDSMITH", 1392716612410544299)
    ROLE_SNIPER = int_env("ROLE_SNIPER", 1392716717255557150)
    ROLE_NIGHT_OWL = int_env("ROLE_NIGHT_OWL", 1392716859161448478)
    ROLE_COMEBACK_KID = int_env("ROLE_COMEBACK_KID", 1392716982582902905)
    ROLE_GHOSTBUSTER = int_env("ROLE_GHOSTBUSTER", 1392717092658352289)
    # ----- inactivity flags (env vars)
    ROLE_SHADOW_FLAG = int_env("ROLE_SHADOW_FLAG", 1391977459850809425)
    ROLE_LURKER_FLAG = int_env("ROLE_LURKER_FLAG", 1391978324510642258)
    ROLE_NPC_FLAG = int_env("ROLE_NPC_FLAG", 1391978703566934087)
    TIERED_BADGES = {
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

# ─── Optional overrides via env‑vars ───────────────────────────────────────
INACTIVE_DAYS = int_env("INACTIVE_DAYS", 14)
DAILY_PROMPT_ENABLED = bool_env("DAILY_PROMPT_ENABLED", False)

# ─── Daily Prompt Schedule ─────────────────────────────────────────────────
# Schedule time in LA timezone (America/Los_Angeles)
# Experiment with different times to optimize engagement
PROMPT_SCHEDULE_HOUR = int_env("PROMPT_SCHEDULE_HOUR", 12)
PROMPT_SCHEDULE_MINUTE = int_env("PROMPT_SCHEDULE_MINUTE", 30)
# Ratio of polls vs text prompts (0.0 = all text, 1.0 = all polls)
PROMPT_POLL_RATIO = float(os.getenv("PROMPT_POLL_RATIO", "0.4"))

# ─── Streak milestone roles ───────────────────────────────────────────────────
# Create these roles in Discord and add the IDs via env vars.
# Milestones: 7, 14, 30, 60, 100 consecutive days of activity.
STREAK_ROLES: dict[int, int] = {
    7: int_env("ROLE_STREAK_7", 0),     # Week Warrior
    14: int_env("ROLE_STREAK_14", 0),   # Fortnight Fighter
    30: int_env("ROLE_STREAK_30", 0),   # Month Master
    60: int_env("ROLE_STREAK_60", 0),   # Iron Will
    100: int_env("ROLE_STREAK_100", 0), # Century Club
}

# Whether streak roles are cumulative (all lower tiers) or exclusive (highest only)
STREAK_ROLES_CUMULATIVE = bool_env("STREAK_ROLES_CUMULATIVE", False)

# ─── Streak milestone celebrations ─────────────────────────────────────────
# Channel to post milestone announcements (defaults to LOBBY_CHANNEL_ID)
MILESTONE_CHANNEL_ID = int_env("MILESTONE_CHANNEL_ID", 0)  # 0 = use LOBBY_CHANNEL_ID
# Whether to use LLM for personalized celebration messages
MILESTONE_LLM_ENABLED = bool_env("MILESTONE_LLM_ENABLED", True)

# ─── Celebrate Command ────────────────────────────────────────────────────
# GIPHY_API_KEY: API key for Giphy GIF service (set in .env)
# Whether to use LLM for personalized celebration messages
CELEBRATE_LLM_ENABLED = bool_env("CELEBRATE_LLM_ENABLED", True)

# ─── Trending / What's Hot ─────────────────────────────────────────────────
# Channel for trending content posts (defaults to LOBBY_CHANNEL_ID)
TRENDING_CHANNEL_ID = int_env("TRENDING_CHANNEL_ID", 0)  # 0 = use LOBBY_CHANNEL_ID
# Whether to auto-post trending digest daily
TRENDING_AUTO_POST = bool_env("TRENDING_AUTO_POST", False)
# Hour (0-23) to post daily trending digest (in LA timezone)
TRENDING_AUTO_POST_HOUR = int_env("TRENDING_AUTO_POST_HOUR", 18)
# Minimum reactions for a message to appear in trending
TRENDING_MIN_REACTIONS = int_env("TRENDING_MIN_REACTIONS", 3)

# IDs of roles automatically assigned by RolesCog
AUTO_ROLE_IDS = {
    ROLE_GHOST,
    ROLE_TOP_POSTER,
    ROLE_CERTIFIED_BANGER,
    ROLE_TOP_CURATOR,
    ROLE_EARLY_BIRD,
    ROLE_SUMMONER,
    ROLE_LORE_CREATOR,
    ROLE_REACTION_ENGINEER,
    ROLE_GALAXY_BRAIN,
    ROLE_WORDSMITH,
    ROLE_SNIPER,
    ROLE_NIGHT_OWL,
    ROLE_COMEBACK_KID,
    ROLE_GHOSTBUSTER,
    ROLE_SHADOW_FLAG,
    ROLE_LURKER_FLAG,
    ROLE_NPC_FLAG,
}

# Descriptive text for automatically assigned roles
ROLE_DESCRIPTIONS: dict[int, str] = {
    ROLE_TOP_POSTER: "Most messages in the last 14 days",
    ROLE_CERTIFIED_BANGER: "Highest laugh reaction ratio (min 10 msgs) in the last 14 days",
    ROLE_TOP_CURATOR: "Shared the most popular rich posts in the last 14 days",
    ROLE_EARLY_BIRD: "Most messages between 5am and 8:30am PT in the last 14 days",
    ROLE_SUMMONER: "Most mentions of others in the last 30 days",
    ROLE_LORE_CREATOR: "Most replied-to user in the last 30 days",
    ROLE_REACTION_ENGINEER: "Created emojis used most as reactions in the last 30 days",
    ROLE_GALAXY_BRAIN: "Longest single message in the last 5 days",
    ROLE_WORDSMITH: "Highest average words per message (min 3) in the last 5 days",
    ROLE_SNIPER: "Best reactions-per-word ratio in the last 5 days",
    ROLE_NIGHT_OWL: "Most messages between 10pm and 4am PT in the last 14 days",
    ROLE_COMEBACK_KID: "Most mentioned user in the last 14 days",
    ROLE_GHOSTBUSTER: "Broke a chat lull exceeding 24 hours",
    ROLE_GHOST: "No messages or reactions in the last 14 days",
    ROLE_SHADOW_FLAG: "No messages in 14 days but mentioned or reacted to in 30 days",
    ROLE_LURKER_FLAG: "1–5 messages or up to 15 reactions in the last 14 days",
    ROLE_NPC_FLAG: "Active without long or rich posts in the last 30 days",
}


# Helper: convenience log line
logging.getLogger(__name__).info("Loaded %s env for Guild %s", env, GUILD_ID)
