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
from .util import int_env
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
    MARKET_CHANNEL_ID = int_env("MARKET_CHANNEL_ID", 0)
    F1_DISCORD_CHANNEL_ID = 1135418490979893321 #test channel for f1_bot.py
    DAILY_PING_CHANNEL = 1374238199676928070
    MONEY_TALK_CHANNEL = int_env("MONEY_TALK_CHANNEL", 1374238246468456469)

    # -------- ROLES --------
    ROLE_GHOST = 1374598613514063942
    # ----- engagement badges (env vars)
    ROLE_TOP_POSTER = int_env("ROLE_TOP_POSTER", 0)
    ROLE_CERTIFIED_BANGER = int_env("ROLE_CERTIFIED_BANGER", 0)
    ROLE_TOP_CURATOR = int_env("ROLE_TOP_CURATOR", 0)
    ROLE_FIRST_DROP = int_env("ROLE_FIRST_DROP", 0)
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
    DAILY_PING_CHANNEL = 1136095810510143518
    MONEY_TALK_CHANNEL = int_env("MONEY_TALK_CHANNEL", 1160414402076491878)


    # -------- ROLES --------
    ROLE_GHOST = 1373545254497816626
    # ----- engagement badges (env vars)
    ROLE_TOP_POSTER = int_env("ROLE_TOP_POSTER", 1391637786406289508)
    ROLE_CERTIFIED_BANGER = int_env("ROLE_CERTIFIED_BANGER", 1391637939900907661)
    ROLE_TOP_CURATOR = int_env("ROLE_TOP_CURATOR", 1391638247570149400)
    ROLE_FIRST_DROP = int_env("ROLE_FIRST_DROP", 1391638519667228672)
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

# ─── Optional overrides via env‑vars ───────────────────────────────────────
INACTIVE_DAYS = int_env("INACTIVE_DAYS", 14)

# Helper: convenience log line
logging.getLogger(__name__).info("Loaded %s env for Guild %s", env, GUILD_ID)
