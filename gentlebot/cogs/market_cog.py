"""
MarketCog – stock charts, market mood, and weekly prediction game.
================================================================
Refactor of the original ``market_bot.py`` into a discord.py **Cog** and
merged with the ``markets`` cog.  Provides advanced chart commands plus a
quick market sentiment snapshot and small bullish/bearish betting game.

Slash commands shipped
----------------------
``/stock``     – fancy chart + key stats, supports ``1d`` · ``1w`` · ``1mo`` · ``3mo`` · ``6mo`` · ``ytd`` · ``1y`` · ``2y`` · ``5y`` · ``10y``
``/earnings``  – next earnings date
``/marketmood`` – quick US market snapshot
``/marketbet``  – place a weekly bull/bear bet or toggle reminders

All IDs, tokens, and embed colours live in **bot_config.py**.
Requires: discord.py v2+, yfinance, matplotlib, pandas, python-dateutil,
requests, sqlite3.
"""

from __future__ import annotations

import io
from datetime import datetime, time, timedelta
from typing import Tuple, Optional, Literal
import logging
import asyncio
import sqlite3
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks
from ..util import chan_name, user_name
import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pytz
import yfinance as yf
from yfinance.exceptions import YFRateLimitError
import requests
import pandas as pd

from .. import bot_config as cfg

# Use a hierarchical logger so messages propagate to the main gentlebot logger
log = logging.getLogger(f"gentlebot.{__name__}")

# ── ENV -------------------------------------------------------------------
TOKEN    = cfg.TOKEN
GUILD_ID = cfg.GUILD_ID
NY       = pytz.timezone("America/New_York")
NY_TZ    = ZoneInfo("US/Eastern")
PT_TZ    = ZoneInfo("US/Pacific")
DB_PATH  = "marketbet.db"
SCHEMA   = "market_game"
CACHE_TTL = timedelta(minutes=10)


def _week_start(ts: datetime) -> datetime:
    monday = ts.date() - timedelta(days=ts.weekday())
    return datetime.combine(monday, time(0, 0), tzinfo=ts.tzinfo)

# ─────────────────────────────────────────────────────────────────────────────
class MarketCog(commands.Cog):
    """Stock‑market slash commands with polished charts."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = requests.Session()
        self.cache: dict[str, tuple[datetime, dict]] = {}
        self._init_db()
        self.summary_task.start()
        self.reminder_task.start()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(DB_PATH)
        conn.execute(f"ATTACH DATABASE '{DB_PATH}' AS {SCHEMA}")
        return conn

    # ─── helpers ────────────────────────────────────────────────────────────
    @staticmethod
    def _period_map(period: str) -> Tuple[str, str]:
        return {
            "1d":  ("1d",  "1m"),
            "1w":  ("7d",  "5m"),
            "1mo": ("1mo", "1d"),
            "3mo": ("3mo", "1d"),
            "6mo": ("6mo", "1d"),
            "ytd": ("ytd", "1d"),
            "1y":  ("1y",  "1d"),
            "2y":  ("2y",  "1wk"),
            "5y":  ("5y",  "1wk"),
            "10y": ("10y", "1mo"),
        }[period]

    def _fetch_history(self, tk: yf.Ticker, period: str) -> pd.DataFrame:
        fetch, interval = self._period_map(period)
        hist = tk.history(period=fetch, interval=interval, prepost=False)

        # normalise index tz to NY for intraday ranges
        if not hist.empty and hist.index.tz is None:
            hist.index = hist.index.tz_localize("UTC").tz_convert(NY)
        elif not hist.empty:
            hist.index = hist.index.tz_convert(NY)

        if period == "1d":
            hist = hist.between_time(time(9, 30), time(16, 0))
            hist = hist[hist.index.weekday < 5]
        return hist

    def _chart_png(self, df: pd.DataFrame, symbol: str, period: str) -> io.BytesIO:
        plt.style.use("seaborn-v0_8-whitegrid")
        fig, ax = plt.subplots(figsize=(6, 3))
        ax.plot(df.index, df["Close"], linewidth=1.6, color="#2081C3")
        ax.set_title(f"{symbol} – {period.upper()} close", fontsize=9)
        ax.tick_params(labelsize=7)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d" if period in ("1d","1w","1mo") else "%Y-%m"))
        fig.tight_layout(pad=1.0)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=120)
        plt.close(fig)
        buf.seek(0)
        return buf

    # ─── /stock command ─────────────────────────────────────────────────────
    period_choices = [
        ("1 Day", "1d"), ("1 Week", "1w"), ("1 Month", "1mo"), ("3 Months", "3mo"),
        ("6 Months", "6mo"), ("YTD", "ytd"), ("1 Year", "1y"), ("2 Years", "2y"),
        ("5 Years", "5y"), ("10 Years", "10y"),
    ]

    @app_commands.command(name="stock", description="Stock chart + key stats")
    @app_commands.describe(symbol="Ticker symbol", period="Time period")
    @app_commands.choices(period=[app_commands.Choice(name=n, value=v) for n,v in period_choices])
    async def stock(self, itx: discord.Interaction, symbol: str, period: app_commands.Choice[str]):
        log.info("/stock invoked by %s in %s", user_name(itx.user), chan_name(itx.channel))
        await itx.response.defer(thinking=True)
        symbol = symbol.upper()
        tk = yf.Ticker(symbol)
        df = self._fetch_history(tk, period.value)
        if df.empty:
            await itx.followup.send("No data found for that ticker.")
            return

        buf = self._chart_png(df, symbol, period.value)
        file = discord.File(buf, filename=f"{symbol}.png")

        info = tk.info or {}
        desc_map = {
            "currentPrice": "Price",
            "previousClose": "Prev Close",
            "dayHigh": "High",
            "dayLow": "Low",
            "marketCap": "Mkt Cap",
            "volume": "Vol",
        }
        lines = []
        for key, label in desc_map.items():
            val = info.get(key)
            if val is None:
                continue
            if isinstance(val, (int, float)):
                val = f"{val:,.2f}" if key != "marketCap" else f"{val/1e9:,.1f} B"
            lines.append(f"**{label}:** {val}")

        embed = discord.Embed(title=f"{symbol} Snapshot", colour=0x2081C3, description="\n".join(lines))
        embed.set_image(url=f"attachment://{symbol}.png")
        await itx.followup.send(embed=embed, file=file)

    # ─── /earnings command ──────────────────────────────────────────────────
    @app_commands.command(name="earnings", description="Next earnings date for a ticker")
    @app_commands.describe(symbol="Ticker symbol")
    async def earnings(self, itx: discord.Interaction, symbol: str):
        log.info("/earnings invoked by %s in %s", user_name(itx.user), chan_name(itx.channel))
        await itx.response.defer(thinking=True)
        tk = yf.Ticker(symbol.upper())
        try:
            cal, eps_est, rev_est = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: (
                        tk.calendar,
                        tk.earnings_estimate,
                        tk.revenue_estimate,
                    )
                ),
                timeout=10,
            )
        except asyncio.TimeoutError:
            log.exception("Timeout retrieving earnings for %s", symbol)
            await itx.followup.send("Could not retrieve earnings data right now.")
            return
        except YFRateLimitError:
            log.warning("Rate limit hit retrieving earnings for %s", symbol)
            await itx.followup.send("Yahoo Finance rate limit reached. Please try again later.")
            return
        except Exception:
            log.exception("Error retrieving earnings for %s", symbol)
            await itx.followup.send("Could not retrieve earnings data right now.")
            return
        if not cal or "Earnings Date" not in cal or not cal["Earnings Date"]:
            await itx.followup.send("No upcoming earnings date found.")
            return
        date = cal["Earnings Date"][0]
        if hasattr(date, "to_pydatetime"):
            date = date.to_pydatetime()
        msg = f"Next earnings call for **{symbol.upper()}**: **{date:%Y-%m-%d}**"
        if not eps_est.empty and "avg" in eps_est.columns and "0q" in eps_est.index:
            eps_val = eps_est.loc["0q"]["avg"]
            if pd.notna(eps_val):
                msg += f"\nAnalysts expect **EPS {eps_val:.2f}**"
        if not rev_est.empty and "avg" in rev_est.columns and "0q" in rev_est.index:
            rev_val = rev_est.loc["0q"]["avg"]
            if pd.notna(rev_val):
                msg += f", revenue **${rev_val/1e9:,.0f}B**"
        await itx.followup.send(msg)

    # ─── DB Helpers ──────────────────────────────────────────────────────
    def _init_db(self):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {SCHEMA}.bets (week TEXT, user INTEGER, direction TEXT, weight INTEGER)"
        )
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {SCHEMA}.scores (user INTEGER PRIMARY KEY, points INTEGER)"
        )
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {SCHEMA}.reminders (user INTEGER PRIMARY KEY, enabled INTEGER)"
        )
        cur.execute(
            f"CREATE TABLE IF NOT EXISTS {SCHEMA}.task_execution (task_name TEXT, execution_key TEXT, executed_at TEXT, PRIMARY KEY (task_name, execution_key))"
        )
        conn.commit()
        conn.close()

    def _place_bet(self, user_id: int, week: str, direction: str, weight: int) -> bool:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM {SCHEMA}.bets WHERE week=? AND user=?", (week, user_id))
        if cur.fetchone():
            conn.close()
            return False
        cur.execute(
            f"INSERT INTO {SCHEMA}.bets (week, user, direction, weight) VALUES (?,?,?,?)",
            (week, user_id, direction, weight),
        )
        conn.commit()
        conn.close()
        return True

    def _toggle_reminder(self, user_id: int, enable: bool):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO {SCHEMA}.reminders(user, enabled) VALUES(?, ?) ON CONFLICT(user) DO UPDATE SET enabled=excluded.enabled",
            (user_id, 1 if enable else 0),
        )
        conn.commit()
        conn.close()

    def _get_reminder_users(self) -> list[int]:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(f"SELECT user FROM {SCHEMA}.reminders WHERE enabled=1")
        rows = cur.fetchall()
        conn.close()
        return [r[0] for r in rows]

    def _reminder_enabled(self, user_id: int) -> bool:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(f"SELECT enabled FROM {SCHEMA}.reminders WHERE user=?", (user_id,))
        row = cur.fetchone()
        conn.close()
        return bool(row and row[0])

    def _record_scores(self, week: str, outcome: str):
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            f"SELECT user, weight FROM {SCHEMA}.bets WHERE week=? AND direction=?",
            (week, outcome),
        )
        winners = cur.fetchall()
        for user_id, points in winners:
            cur.execute(
                f"INSERT INTO {SCHEMA}.scores(user, points) VALUES(?, ?) ON CONFLICT(user) DO UPDATE SET points=points+excluded.points",
                (user_id, points),
            )
        cur.execute(f"DELETE FROM {SCHEMA}.bets WHERE week=?", (week,))
        conn.commit()
        cur.execute(
            f"SELECT user, points FROM {SCHEMA}.scores ORDER BY points DESC LIMIT 5"
        )
        leaderboard = cur.fetchall()
        conn.close()
        return winners, leaderboard

    def _bets_exist(self, week: str) -> bool:
        """Return True if any bets exist for the given week."""
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM {SCHEMA}.bets WHERE week=? LIMIT 1", (week,))
        row = cur.fetchone()
        conn.close()
        return row is not None

    def _task_already_executed(self, task_name: str, key: str) -> bool:
        """Check if a task has already been executed with the given key."""
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            f"SELECT 1 FROM {SCHEMA}.task_execution WHERE task_name=? AND execution_key=?",
            (task_name, key),
        )
        row = cur.fetchone()
        conn.close()
        return row is not None

    def _mark_task_executed(self, task_name: str, key: str) -> None:
        """Mark a task as executed with the given key."""
        from datetime import datetime
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            f"INSERT OR REPLACE INTO {SCHEMA}.task_execution (task_name, execution_key, executed_at) VALUES (?, ?, ?)",
            (task_name, key, datetime.now().isoformat()),
        )
        conn.commit()
        conn.close()

    # ─── Fetch Helpers ───────────────────────────────────────────────────
    async def _quote_pct(self, symbol: str) -> Optional[float]:
        try:
            info = await asyncio.to_thread(lambda: yf.Ticker(symbol).info)
            price = info.get("regularMarketPrice")
            prev = info.get("regularMarketPreviousClose")
            if price is not None and prev:
                return (price - prev) / prev * 100
        except Exception:
            log.exception("Quote failed for %s", symbol)
        return None

    async def _quote_price(self, symbol: str) -> Optional[float]:
        try:
            info = await asyncio.to_thread(lambda: yf.Ticker(symbol).info)
            price = info.get("regularMarketPrice")
            if price is not None:
                return float(price)
        except Exception:
            log.exception("Price fetch failed for %s", symbol)
        return None

    async def _fetch_put_call(self) -> Optional[float]:
        url = "https://cdn.cboe.com/api/global/delayed_quotes/special_statistics.json"
        try:
            resp = await asyncio.to_thread(self.session.get, url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            val = data.get("specialStatistics", {}).get("equityPutCallRatio", {}).get("value")
            return float(val) if val else None
        except Exception:
            log.exception("Failed to fetch put/call ratio")
            return None

    async def _fetch_breadth(self) -> Optional[float]:
        url = "https://finviz.com/api/breadth.ashx"
        try:
            resp = await asyncio.to_thread(self.session.get, url, timeout=10)
            resp.raise_for_status()
            j = resp.json()
            adv = j.get("advancers")
            dec = j.get("decliners")
            if adv is not None and dec is not None and adv + dec > 0:
                return adv / (adv + dec) * 100
        except Exception:
            log.exception("Failed to fetch breadth")
        return None

    async def _fetch_trending(self) -> list[str]:
        url = "https://finviz.com/api/trending.ashx"
        try:
            resp = await asyncio.to_thread(self.session.get, url, timeout=10)
            resp.raise_for_status()
            j = resp.json()
            return [item["ticker"] for item in j.get("quotes", [])]
        except Exception:
            log.exception("Failed to fetch trending tickers")
            return []

    async def _gather_data(self) -> dict:
        now = datetime.now(tz=NY_TZ)
        cache_key = now.strftime("%Y%m%d%H")  # hourly cache
        cached = self.cache.get(cache_key)
        if cached and now - cached[0] < CACHE_TTL:
            return cached[1]
        sp, ndx, vix, pcr, breadth, trending = await asyncio.gather(
            self._quote_pct("^GSPC"),
            self._quote_pct("^NDX"),
            self._quote_price("^VIX"),
            self._fetch_put_call(),
            self._fetch_breadth(),
            self._fetch_trending(),
        )
        data = {
            "sp_pct": sp,
            "ndx_pct": ndx,
            "vix": vix,
            "pcr": pcr,
            "breadth": breadth,
            "trending": trending,
            "timestamp": now,
        }
        self.cache[cache_key] = (now, data)
        return data

    # ─── Additional Commands ─────────────────────────────────────────────
    @app_commands.command(name="marketmood", description="US market sentiment snapshot")
    @app_commands.describe(ephemeral="Only you can see the response")
    async def marketmood(self, itx: discord.Interaction, ephemeral: Optional[bool] = False):
        log.info("/marketmood invoked by %s in %s", user_name(itx.user), chan_name(itx.channel))
        await itx.response.defer(thinking=True, ephemeral=ephemeral)
        data = await self._gather_data()
        ts = data["timestamp"].astimezone(PT_TZ).strftime("%b %d, %-I:%M %p PT")
        sp_pct = data["sp_pct"]
        ndx_pct = data["ndx_pct"]
        vix = data["vix"]
        pcr = data["pcr"]
        breadth = data["breadth"]
        mood_emoji = "📈" if (sp_pct or 0) > 0 else "📉"
        lines = [f"{mood_emoji} **Market Mood — {ts}**", ""]

        if sp_pct is not None:
            emo = "🔺" if sp_pct > 0 else "🔻"
            lines.append(f"**S&P 500:** {emo} {sp_pct:+.1f}%")
        if ndx_pct is not None:
            emo = "🔺" if ndx_pct > 0 else "🔻"
            lines.append(f"**NASDAQ 100:** {emo} {ndx_pct:+.1f}%")
        if isinstance(vix, (int, float)):
            lines.append(f"**VIX:** ⚠️ {vix:.1f}")
        if pcr is not None:
            lines.append(f"**Put/Call:** {pcr:.2f}")
        if breadth is not None:
            lines.append(f"**Breadth:** {breadth:.0f}% advancers")

        lines.append("")
        lines.append("📊 *Data: Yahoo Finance · CBOE · Finviz*")
        lines.append("⚠️ *Not financial advice*")

        await itx.followup.send("\n".join(lines), ephemeral=ephemeral)

    @app_commands.command(name="marketbet", description="Place a weekly bull/bear bet or set reminder")
    @app_commands.describe(direction="bullish or bearish", reminder="Enable DM reminder on Monday")
    async def marketbet(self, itx: discord.Interaction, direction: Optional[Literal["bullish", "bearish"]] = None, reminder: Optional[bool] = None):
        log.info("/marketbet invoked by %s in %s", user_name(itx.user), chan_name(itx.channel))
        await itx.response.defer(thinking=True, ephemeral=True)
        now = datetime.now(NY_TZ)
        week_start = _week_start(now)
        week = week_start.date().isoformat()

        reminder_state = self._reminder_enabled(itx.user.id)
        if reminder is not None:
            self._toggle_reminder(itx.user.id, reminder)
            reminder_state = reminder

        messages = []
        if direction:
            day_index = min(now.weekday(), 4)
            weight = int((5 - day_index) / 5 * 100)
            placed = self._place_bet(itx.user.id, week, direction, weight)
            if placed:
                emoji = "📈" if direction == "bullish" else "📉"
                label = "BULLISH" if direction == "bullish" else "BEARISH"
                lines = [
                    "🎯 **Bet Locked In!**",
                    "",
                    f"**{itx.user.mention}**, your **{emoji} {label}** bet for the **Week of {week_start:%b %d}** is **locked.**",
                    "",
                    "**Bet Details:**",
                    f" **Weight:** {weight} pts (placed {now:%A})",
                    " **Results:** Friday @ 1:00 PM PT",
                    f" **Reminder:** DM {'enabled' if reminder_state else 'disabled'}",
                ]
                messages.append("\n".join(lines))
            else:
                messages.append("You already placed a bet this week.")
                if reminder is not None:
                    state = "enabled" if reminder else "disabled"
                    messages.append(f"DM reminder {state}.")
        else:
            if reminder is not None:
                state = "enabled" if reminder else "disabled"
                messages.append(f"DM reminder {state}.")
            else:
                messages.append("Specify a direction or reminder option.")

        await itx.followup.send("\n".join(messages), ephemeral=True)

    # ─── Tasks ────────────────────────────────────────────────────────────
    async def _week_open_close(self) -> tuple[Optional[float], Optional[float]]:
        """Fetch Monday open and Friday close for SPY."""

        def fetch() -> tuple[Optional[float], Optional[float]]:
            start = _week_start(datetime.now(NY_TZ)).date()
            end = start + timedelta(days=5)
            hist = yf.download("SPY", start=start, end=end, interval="1d", progress=False)
            if hist.empty:
                return None, None
            monday_open = float(hist.iloc[0]["Open"])
            friday_close = float(hist.iloc[-1]["Close"])
            return monday_open, friday_close

        try:
            return await asyncio.to_thread(fetch)
        except Exception:
            log.exception("Failed to fetch weekly prices")
            return None, None

    @tasks.loop(time=time(13, 0, tzinfo=PT_TZ))
    async def summary_task(self):
        now = datetime.now(PT_TZ)
        if now.weekday() != 4:
            return
        week = _week_start(now).date().isoformat()
        if not self._bets_exist(week):
            return

        # Idempotency check: skip if already processed this week
        execution_key = f"{week}-summary"
        if self._task_already_executed("market_summary", execution_key):
            log.info("Market summary already processed for week %s; skipping", week)
            return

        monday_open, friday_close = await self._week_open_close()
        if monday_open is None or friday_close is None:
            return
        pct = (friday_close - monday_open) / monday_open * 100
        outcome = "bullish" if pct >= 0 else "bearish"
        winners, board = self._record_scores(week, outcome)

        # Mark as executed before sending message (to prevent duplicates on send failure)
        self._mark_task_executed("market_summary", execution_key)

        channel = self.bot.get_channel(cfg.MONEY_TALK_CHANNEL)
        if not channel:
            log.error("Money Talk channel not found")
            return
        lines = [f"**Week of {week} Result: {'🐂 Bullish' if outcome=='bullish' else '🐻 Bearish'} ({pct:+.1f}%)**"]
        for uid, weight in winners:
            user = self.bot.get_user(uid)
            mention = user.mention if user else str(uid)
            lines.append(f"✅ {mention} — {weight} pts")
        embed = discord.Embed(title="Market Bet Results", description="\n".join(lines), colour=0x3498DB)
        if board:
            lb_lines = [f"{i+1}. <@{uid}> – {pts} pts" for i, (uid, pts) in enumerate(board)]
            embed.add_field(name="Leaderboard", value="\n".join(lb_lines), inline=False)
        await channel.send(embed=embed)

    @summary_task.before_loop
    async def before_summary(self):
        await self.bot.wait_until_ready()

    @tasks.loop(time=time(7, 0, tzinfo=PT_TZ))
    async def reminder_task(self):
        now = datetime.now(PT_TZ)
        if now.weekday() != 0:
            return
        week = _week_start(now).date().isoformat()
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(f"SELECT user FROM {SCHEMA}.bets WHERE week=?", (week,))
        already = {row[0] for row in cur.fetchall()}
        conn.close()
        users = self._get_reminder_users()
        for uid in users:
            if uid in already:
                continue
            user = self.bot.get_user(uid)
            if not user:
                continue
            try:
                await user.send("Don't forget to place your /marketbet for this week!")
            except Exception:
                log.exception("Failed to DM reminder to %s", uid)

    @reminder_task.before_loop
    async def before_reminder(self):
        await self.bot.wait_until_ready()

    def cog_unload(self):
        self.summary_task.cancel()
        self.reminder_task.cancel()
        self.session.close()

# ─── Loader ────────────────────────────────────────────────────────────────
async def setup(bot: commands.Bot):
    await bot.add_cog(MarketCog(bot))




# # market_bot.py
# #!/usr/bin/env python3
# """
# Discord Gentlebot – slash‑first stock command with polished chart styling.
# Volume pane removed per latest request.
# """
# import os, io, pytz, numpy as np
# import discord
# from discord import app_commands
# from dotenv import load_dotenv
# import yfinance as yf
# import matplotlib
# matplotlib.use("Agg")
# import matplotlib.pyplot as plt
# import matplotlib.dates as mdates
# import matplotlib as mpl
# from datetime import time

# # ── ENV -------------------------------------------------------------------
# load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
# TOKEN    = os.getenv("DISCORD_TOKEN")
# GUILD_ID = int(os.getenv("DISCORD_GUILD_ID"))

# # ── DISCORD ---------------------------------------------------------------
# intents = discord.Intents.default()
# client  = discord.Client(intents=intents)
# tree    = app_commands.CommandTree(client)

# @client.event
# async def on_ready():
#     print(f"Client ready. GUILD_ID={GUILD_ID}")
#     guild = discord.Object(id=GUILD_ID)
#     tree.clear_commands(guild=guild)          # wipe stale
#     tree.copy_global_to(guild=guild)          # copy globals ➜ guild
#     cmds = await tree.sync(guild=guild)
#     print(f"✅ Synced {len(cmds)} commands to guild")

# # ── /stock ----------------------------------------------------------------
# @tree.command(name="stock", description="Fetch stock chart + key stats")
# @app_commands.describe(symbol="Ticker (e.g. AAPL)",
#                        period="1d · 1w · 1mo · 3mo · 6mo · ytd · 1y · 2y · 5y · 10y")
# @app_commands.choices(period=[
#     app_commands.Choice(name=n, value=v) for n, v in [
#         ("1 Day","1d"),("1 Week","1w"),("1 Month","1mo"),("3 Months","3mo"),
#         ("6 Months","6mo"),("YTD","ytd"),("1 Year","1y"),("2 Years","2y"),
#         ("5 Years","5y"),("10 Years","10y")]
# ])
# async def stock(interaction: discord.Interaction, symbol: str, period: app_commands.Choice[str]):
#     await interaction.response.defer()
#     symbol, pv = symbol.upper(), period.value

#     # fetch map -------------------------------------------------------------
#     ivmap = {
#         '1d':  ('1d',  '1m'),
#         '1w':  ('7d',  '5m'),
#         '1mo': ('1mo', '1d'),
#         '3mo': ('3mo', '1d'),
#         '6mo': ('6mo', '1d'),
#         'ytd': ('ytd', '1d'),
#         '1y':  ('1y',  '1d'),
#         '2y':  ('2y',  '1wk'),
#         '5y':  ('5y',  '1wk'),
#         '10y': ('10y', '1mo'),
#     }
#     fetch, interval = ivmap[pv]
#     tk, ny = yf.Ticker(symbol), pytz.timezone('America/New_York')

#     if pv == '1d':
#         hist = tk.history(period='1d', interval='1m', prepost=False)
#         idx  = hist.index.tz_localize('UTC').tz_convert(ny) if hist.index.tz is None else hist.index.tz_convert(ny)
#         hist.index = idx
#         hist = hist.between_time(time(9,30), time(16,0))
#         hist = hist[hist.index.weekday < 5]
#     elif pv == '1w':
#         hist = tk.history(period='7d', interval='5m', prepost=False)
#         idx  = hist.index.tz_localize('UTC').tz_convert(ny) if hist.index.tz is None else hist.index.tz_convert(ny)
#         hist.index = idx
#         hist = hist.between_time(time(9,30), time(16,0))
#         hist = hist[hist.index.weekday < 5]
#     else:
#         hist = tk.history(period=fetch, interval=interval)

#     if hist.empty:
#         await interaction.followup.send(f"❌ No data for `{symbol}` over `{pv}`."); return

#     first, last = hist['Close'].iloc[0], hist['Close'].iloc[-1]
#     delta, pct = last-first, (last-first)/first*100
#     colour = 0x2ECC71 if delta>=0 else 0xE74C3C
#     fg = "white"

#     # ─ plot (single pane) ---------------------------------------------------
#     fig, ax1 = plt.subplots(figsize=(5,4))
#     fig.patch.set_alpha(0)
#     ax1.set_facecolor("none")
#     ax1.tick_params(colors=fg)
#     for loc, spine in ax1.spines.items():
#         spine.set_color(fg)
#         spine.set_linewidth(0.75 if loc == 'bottom' else 0)
#     # move price axis to the right side
#     ax1.yaxis.tick_right()
#     ax1.yaxis.set_label_position("right")
#     ax1.title.set_color(fg)

#             # price line
#     x_vals = np.arange(len(hist)) if pv == '1w' else hist.index
#     ax1.plot(x_vals, hist['Close'], color=f"#{colour:06X}", lw=1.5, zorder=3)

#     # gradient fill under curve — dark at line, fades to transparent
#     baseline = hist['Close'].min()

#     # draw invisible fill to get path for clipping
#     invisible = ax1.fill_between(x_vals, hist['Close'], baseline, color='none')
#     clip_path = (invisible.get_paths()[0], ax1.transData)

#         # create a vertical gradient
#     grad = np.linspace(1, 0, 256).reshape(-1, 1)          # 256 rows, 1 column (vertical fade)
#     top_rgba = mpl.colors.to_rgba(f"#{colour:06X}", 0.65) # opaque at the price line
#     bot_rgba = (*top_rgba[:3], 0.0)                        # transparent at baseline
#     cmap = mpl.colors.LinearSegmentedColormap.from_list('fade', [top_rgba, bot_rgba])

#     ax1.imshow(grad,
#                extent=[x_vals[0], x_vals[-1], baseline, hist['Close'].max()],
#                origin='lower', aspect='auto', cmap=cmap, zorder=2,
#                clip_path=clip_path, clip_on=True)

#     # x‑axis labels & limits
#     if pv=='1d':
#         ax1.set_xlim(x_vals[0], x_vals[-1])
#         ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M', tz=ny))
#         fig.autofmt_xdate()
#     elif pv=='1w':
#         days = hist.index.normalize()
#         first = [np.where(days == d)[0][0] for d in np.unique(days)]
#         ax1.set_xticks(first)
#         ax1.set_xticklabels([d.strftime('%d') for d in np.unique(days)], rotation=45, ha='right', color=fg)
#         ax1.set_xlim(x_vals[0], x_vals[-1])
#     else:
#         # Custom date formatting per longer period to mimic iOS Stocks
#         if pv in ('1mo', '3mo'):
#             ax1.xaxis.set_major_locator(mdates.DayLocator(interval=7))      # every week
#             ax1.xaxis.set_major_formatter(mdates.DateFormatter('%d'))    # Apr 25
#         elif pv in ('6mo', 'ytd', '1y'):
#             ax1.xaxis.set_major_locator(mdates.MonthLocator(interval=2))              # each month
#             ax1.xaxis.set_major_formatter(mdates.DateFormatter('%b'))       # Apr
#         else:  # 2y, 5y, 10y
#             ax1.xaxis.set_major_locator(mdates.YearLocator())
#             ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))       # 2025
#         ax1.tick_params(axis='x', rotation=45, colors=fg)

#     ymin, ymax = hist['Close'].min(), hist['Close'].max()
#     ax1.set_ylim(ymin - (ymax - ymin) * 0.1, ymax + (ymax - ymin) * 0.1)
#         # multi‑line title styled like iOS Stocks
#     period_labels = {
#         '1d':'Today','1w':'Past Week','1mo':'Past Month','3mo':'Past 3 Months',
#         '6mo':'Past 6 Months','ytd':'Year to Date','1y':'Past Year','2y':'Past 2 Years',
#         '5y':'Past 5 Years','10y':'Past 10 Years'
#     }
#     title_lines = [f"{symbol}",
#                    f"${last:.2f}   ({pct:+.2f}%)",
#                    period_labels.get(pv, pv)]
#     ax1.set_title("\n".join(title_lines), pad=8, linespacing=1.2, loc='left', color=fg)
#     ax1.grid(True, which='major', alpha=0.1, color=fg)
#     fig.tight_layout()

#     buf=io.BytesIO(); fig.savefig(buf, format='png', transparent=True); buf.seek(0); plt.close(fig)

#     info=tk.info; embed=discord.Embed(title=f"{symbol} · {pv.upper()}", timestamp=hist.index[-1], color=colour)
#     def fld(n,v): embed.add_field(name=n, value=v, inline=True)
#     fld('Price',f"${last:.2f}"); fld('Change',f"${delta:.2f} ({pct:+.2f}%)"); fld('Open',f"${info.get('open',0):.2f}")
#     fld('High',f"${info.get('dayHigh',0):.2f}"); fld('Low',f"${info.get('dayLow',0):.2f}")
#     fld('Mkt Cap',f"{info.get('marketCap',0)/1e9:.1f}B"); fld('P/E',f"{info.get('trailingPE','N/A')}")
#     fld('52W H/L',f"{info.get('fiftyTwoWeekHigh',0):.2f}/{info.get('fiftyTwoWeekLow',0):.2f}"); fld('Avg Vol',f"{info.get('averageVolume',0):,}")
#     embed.set_footer(text=f"Data from Yahoo Finance")
#     await interaction.followup.send(file=discord.File(buf,'chart.png'), embed=embed)

# # ── /earnings stub --------------------------------------------------------
# @tree.command(name='earnings', description='Get upcoming earnings + last call summary')
# @app_commands.describe(symbol='Ticker symbol, e.g. MSFT')
# async def earnings(interaction: discord.Interaction, symbol: str):
#     await interaction.response.defer(); await interaction.followup.send(f"Earnings for {symbol.upper()} coming soon!")

# # ── main ------------------------------------------------------------------
# if __name__=='__main__':
#     client.run(TOKEN)
