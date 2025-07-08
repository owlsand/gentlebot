from __future__ import annotations
"""
Source of truth for IDs & tokens
======================================================
Supports **multi‑env** (TEST vs PROD) so you can run the bot in your sandbox
Guild first, then flip the ENV var when you deploy.

Usage
-----
$ export BOT_ENV=TEST  # or PROD (default PROD)
$ python main.py

* .env (git‑ignored) keeps only TOKEN values*
DISCORD_TOKEN_TEST=xxx
DISCORD_TOKEN_PROD=yyy

You can also inject IDs via env‑vars if you’d rather not commit them.
"""
import os
import logging
from dotenv import load_dotenv
load_dotenv()

# ─── Select env ────────────────────────────────────────────────────────────
env = os.getenv("env", "prod").upper()
IS_TEST = env == "TEST"

# ─── Tokens ───────────────────────────────────────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN")
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY")

# ─── IDs per environment ──────────────────────────────────────────────────
if IS_TEST:
    # -------- TEST SERVER IDs --------
    GUILD_ID = 1135418490979893318
    
    # -------- CHANNELS --------
    FINANCE_CHANNEL_ID=1135418490979893321 #test channel for market_bot.py
    MARKET_CHANNEL_ID = int(os.getenv("MARKET_CHANNEL_ID", 0))
    F1_DISCORD_CHANNEL_ID = 1135418490979893321 #test channel for f1_bot.py
    DAILY_PING_CHANNEL = 1374238199676928070
    MONEY_TALK_CHANNEL = int(os.getenv("MONEY_TALK_CHANNEL", 1374238246468456469))

    # -------- ROLES --------
    ROLE_GHOST = 1374598613514063942
    # ----- engagement badges (env vars)
    ROLE_TOP_POSTER = int(os.getenv("ROLE_TOP_POSTER", 0))
    ROLE_CERTIFIED_BANGER = int(os.getenv("ROLE_CERTIFIED_BANGER", 0))
    ROLE_TOP_CURATOR = int(os.getenv("ROLE_TOP_CURATOR", 0))
    ROLE_FIRST_DROP = int(os.getenv("ROLE_FIRST_DROP", 0))
    ROLE_SUMMONER = int(os.getenv("ROLE_SUMMONER", 0))
    ROLE_LORE_CREATOR = int(os.getenv("ROLE_LORE_CREATOR", 0))
    ROLE_REACTION_ENGINEER = int(os.getenv("ROLE_REACTION_ENGINEER", 0))
    # ----- inactivity flags (env vars)
    ROLE_SHADOW_FLAG = int(os.getenv("ROLE_SHADOW_FLAG", 0))
    ROLE_LURKER_FLAG = int(os.getenv("ROLE_LURKER_FLAG", 0))
    ROLE_NPC_FLAG = int(os.getenv("ROLE_NPC_FLAG", 0))

else:
    # -------- PROD SERVER IDs --------
    GUILD_ID=973284857885126746

    # -------- CHANNELS --------
    FINANCE_CHANNEL_ID=1160414402076491878
    MARKET_CHANNEL_ID = int(os.getenv("MARKET_CHANNEL_ID", 0))
    F1_DISCORD_CHANNEL_ID=1121104901175509106
    DAILY_PING_CHANNEL = 1136095810510143518
    MONEY_TALK_CHANNEL = int(os.getenv("MONEY_TALK_CHANNEL", 1160414402076491878))


    # -------- ROLES --------
    ROLE_GHOST = 1373545254497816626
    # ----- engagement badges (env vars)
    ROLE_TOP_POSTER = int(os.getenv("ROLE_TOP_POSTER", 0))
    ROLE_CERTIFIED_BANGER = int(os.getenv("ROLE_CERTIFIED_BANGER", 0))
    ROLE_TOP_CURATOR = int(os.getenv("ROLE_TOP_CURATOR", 0))
    ROLE_FIRST_DROP = int(os.getenv("ROLE_FIRST_DROP", 0))
    ROLE_SUMMONER = int(os.getenv("ROLE_SUMMONER", 0))
    ROLE_LORE_CREATOR = int(os.getenv("ROLE_LORE_CREATOR", 0))
    ROLE_REACTION_ENGINEER = int(os.getenv("ROLE_REACTION_ENGINEER", 0))
    # ----- inactivity flags (env vars)
    ROLE_SHADOW_FLAG = int(os.getenv("ROLE_SHADOW_FLAG", 0))
    ROLE_LURKER_FLAG = int(os.getenv("ROLE_LURKER_FLAG", 0))
    ROLE_NPC_FLAG = int(os.getenv("ROLE_NPC_FLAG", 0))

# ─── Optional overrides via env‑vars ───────────────────────────────────────
INACTIVE_DAYS = int(os.getenv("INACTIVE_DAYS", 14))

# Helper: convenience log line
logging.getLogger(__name__).info("Loaded %s env for Guild %s", env, GUILD_ID)
