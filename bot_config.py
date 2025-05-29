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
from dotenv import load_dotenv
load_dotenv()

# ─── Select env ────────────────────────────────────────────────────────────
env = os.getenv("env", "prod").upper()
IS_TEST = env == "TEST"

# ─── Tokens ───────────────────────────────────────────────────────────────
TOKEN = os.getenv("DISCORD_TOKEN")

# ─── IDs per environment ──────────────────────────────────────────────────
if IS_TEST:
    # -------- TEST SERVER IDs --------
    GUILD_ID = 1135418490979893318
    
    # -------- CHANNELS --------
    FINANCE_CHANNEL_ID=1135418490979893321 #test channel for market_bot.py
    F1_DISCORD_CHANNEL_ID = 1135418490979893321 #test channel for f1_bot.py
    DAILY_PING_CHANNEL = 1374238199676928070
    MONEY_TALK_CHANNEL = 1374238246468456469
    VANITY_CHANNEL = 1135418490979893321
    VANITY_MESSAGE = 1375937678759034972 # pinned message id
    BUILD_CHANNELS = [1374238288289726484, 222155555555555555]

    # -------- ROLES --------
    ROLE_GHOST = 1374598613514063942
    ROLE_THREADLORD = 1374598720485720175
    ROLE_BUILDER = 1374598790056644618
    ROLE_PROMPT_WIZARD = 1374598832310063114
    ROLE_MONEY_GREMLIN = 1374598897636216902
    ROLE_CHAOS_MVP = 1374598944348311552
    ROLE_MASCOT = 1374598996387041332
    # ----- vanity
    ROLE_CHAOS = 1375938581583102085
    ROLE_COZY = 1375938635030855790
    ROLE_SHADOW = 1375938681088639070
    ROLE_GOBLIN = 1375938744150134947
    ROLE_SAGE = 1375938786868990132
    ROLE_HYPE = 1375938824395292683

else:
    # -------- PROD SERVER IDs --------
    GUILD_ID=973284857885126746

    # -------- CHANNELS --------
    FINANCE_CHANNEL_ID=1160414402076491878
    F1_DISCORD_CHANNEL_ID=1121104901175509106
    DAILY_PING_CHANNEL = 1136095810510143518
    MONEY_TALK_CHANNEL = 1160414402076491878
    BUILD_CHANNELS = [1167564242615029900, 222155555555555555]
    VANITY_CHANNEL = 973284857885126749

    VANITY_MESSAGE = 1373542983730855977 # pinned message id

    # -------- ROLES --------
    ROLE_GHOST = 1373545254497816626
    ROLE_THREADLORD = 1373545667104083979
    ROLE_BUILDER = 1373545780391972977
    ROLE_PROMPT_WIZARD = 1373546301765062708
    ROLE_MONEY_GREMLIN = 1373546418928877588
    ROLE_CHAOS_MVP = 1374599774967435286
    ROLE_MASCOT = 222222222222222222
    # ----- vanity
    ROLE_CHAOS = 1373541467531771986
    ROLE_COZY = 1373541640098025525
    ROLE_SHADOW = 1373541833409564672
    ROLE_GOBLIN = 1373883321142214666
    ROLE_SAGE = 1373883566894874714
    ROLE_HYPE = 1373883736717791264

# ─── Optional overrides via env‑vars ───────────────────────────────────────
INACTIVE_DAYS = int(os.getenv("INACTIVE_DAYS", 14))
THREADLORD_MIN_LEN = int(os.getenv("THREADLORD_MIN_LEN", 300))
THREADLORD_REQUIRED = int(os.getenv("THREADLORD_REQUIRED", 2))
PROMPT_WIZARD_WEEKLY = int(os.getenv("PROMPT_WIZARD_WEEKLY", 5))
MONEY_GREMLIN_WEEKLY = int(os.getenv("MONEY_GREMLIN_WEEKLY", 5))
PROMPT_SCHEDULE_HOUR = 8

# Helper: convenience log line
print(f"[BotConfig] Loaded {env} env for Guild {GUILD_ID}")
