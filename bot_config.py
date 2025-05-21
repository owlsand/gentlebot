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
    F1_DISCORD_CHANNEL_ID=1135418490979893321 #test channel for f1_bot.py
    DAILY_PING_CHANNEL = 222122222222222222
    MONEY_TALK_CHANNEL = 222133333333333333
    BUILD_CHANNELS = [222144444444444444, 222155555555555555]

    # -------- ROLES --------
    ROLE_GHOST = 111101010101010101
    ROLE_THREADLORD = 111102020202020202
    ROLE_BUILDER = 111103030303030303
    ROLE_PROMPT_WIZARD = 111104040404040404
    ROLE_MONEY_GREMLIN = 111105050505050505
    ROLE_CHAOS_MVP = 111106060606060606
    ROLE_MASCOT = 111107070707070707
else:
    # -------- PROD SERVER IDs --------
    GUILD_ID=973284857885126746

    # -------- CHANNELS --------
    FINANCE_CHANNEL_ID=1160414402076491878
    F1_DISCORD_CHANNEL_ID=1121104901175509106
    DAILY_PING_CHANNEL = 222122222222222222
    MONEY_TALK_CHANNEL = 222133333333333333
    BUILD_CHANNELS = [222144444444444444, 222155555555555555]

    # -------- ROLES --------
    ROLE_GHOST = 222166666666666666
    ROLE_THREADLORD = 222177777777777777
    ROLE_BUILDER = 222188888888888888
    ROLE_PROMPT_WIZARD = 222199999999999999
    ROLE_MONEY_GREMLIN = 222200000000000000
    ROLE_CHAOS_MVP = 222211111111111111
    ROLE_MASCOT = 222222222222222222

# ─── Optional overrides via env‑vars ───────────────────────────────────────
INACTIVE_DAYS = int(os.getenv("INACTIVE_DAYS", 30))
THREADLORD_MIN_LEN = int(os.getenv("THREADLORD_MIN_LEN", 300))
THREADLORD_REQUIRED = int(os.getenv("THREADLORD_REQUIRED", 3))
PROMPT_WIZARD_WEEKLY = int(os.getenv("PROMPT_WIZARD_WEEKLY", 5))
MONEY_GREMLIN_WEEKLY = int(os.getenv("MONEY_GREMLIN_WEEKLY", 5))

# Helper: convenience log line
print(f"[bot_config] Loaded {env} env – guild {GUILD_ID}")
