"""
MarketsCog – market sentiment snapshot and weekly prediction game.

Commands:
  /marketmood [ephemeral] – show quick US equity market sentiment.
  /marketbet direction:[bullish|bearish] reminder:bool – place a weekly bet or opt-in/out of Monday reminders.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo
from typing import Optional, Literal

import discord
from discord import app_commands
from discord.ext import commands, tasks
import yfinance as yf
import requests

import bot_config as cfg
from util import chan_name

log = logging.getLogger(__name__)

NY_TZ = ZoneInfo("US/Eastern")
PT_TZ = ZoneInfo("US/Pacific")

DB_PATH = "marketbet.db"
CACHE_TTL = timedelta(minutes=10)


def _week_start(ts: datetime) -> datetime:
    monday = ts.date() - timedelta(days=ts.weekday())
    return datetime.combine(monday, time(0, 0), tzinfo=ts.tzinfo)


class MarketsCog(commands.Cog):
    """Market summary and weekly bullish/bearish game."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = requests.Session()
        self.cache: dict[str, tuple[datetime, dict]] = {}
        self._init_db()
        self.summary_task.start()
        self.reminder_task.start()

    # ─── DB Helpers ──────────────────────────────────────────────────────
    def _init_db(self):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE IF NOT EXISTS bets (week TEXT, user INTEGER, direction TEXT, weight INTEGER)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS scores (user INTEGER PRIMARY KEY, points INTEGER)"
        )
        cur.execute(
            "CREATE TABLE IF NOT EXISTS reminders (user INTEGER PRIMARY KEY, enabled INTEGER)"
        )
        conn.commit()
        conn.close()

    def _place_bet(self, user_id: int, week: str, direction: str, weight: int) -> bool:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM bets WHERE week=? AND user=?", (week, user_id))
        if cur.fetchone():
            conn.close()
            return False
        cur.execute(
            "INSERT INTO bets (week, user, direction, weight) VALUES (?,?,?,?)",
            (week, user_id, direction, weight),
        )
        conn.commit()
        conn.close()
        return True

    def _toggle_reminder(self, user_id: int, enable: bool):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO reminders(user, enabled) VALUES(?, ?) ON CONFLICT(user) DO UPDATE SET enabled=excluded.enabled",
            (user_id, 1 if enable else 0),
        )
        conn.commit()
        conn.close()

    def _get_reminder_users(self) -> list[int]:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT user FROM reminders WHERE enabled=1")
        rows = cur.fetchall()
        conn.close()
        return [r[0] for r in rows]

    def _record_scores(self, week: str, outcome: str):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            "SELECT user, weight FROM bets WHERE week=? AND direction=?",
            (week, outcome),
        )
        winners = cur.fetchall()
        for user_id, points in winners:
            cur.execute(
                "INSERT INTO scores(user, points) VALUES(?, ?) ON CONFLICT(user) DO UPDATE SET points=points+excluded.points",
                (user_id, points),
            )
        cur.execute("DELETE FROM bets WHERE week=?", (week,))
        conn.commit()
        cur.execute(
            "SELECT user, points FROM scores ORDER BY points DESC LIMIT 5"
        )
        leaderboard = cur.fetchall()
        conn.close()
        return winners, leaderboard

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

    # ─── Commands ────────────────────────────────────────────────────────
    @app_commands.command(name="marketmood", description="US market sentiment snapshot")
    @app_commands.describe(ephemeral="Only you can see the response")
    async def marketmood(self, itx: discord.Interaction, ephemeral: Optional[bool] = False):
        log.info("/marketmood invoked by %s in %s", itx.user.id, chan_name(itx.channel))
        await itx.response.defer(thinking=True, ephemeral=ephemeral)
        data = await self._gather_data()
        ts = data["timestamp"].astimezone(PT_TZ).strftime("%b %d, %-I:%M %p PT")
        sp_pct = data["sp_pct"]
        ndx_pct = data["ndx_pct"]
        vix = data["vix"]
        pcr = data["pcr"]
        breadth = data["breadth"]
        trending = data["trending"]
        desc = [f"S&P 500: **{sp_pct:+.1f}%**" if sp_pct is not None else "S&P 500: N/A"]
        desc.append(f"NASDAQ 100: **{ndx_pct:+.1f}%**" if ndx_pct is not None else "NASDAQ 100: N/A")
        desc.append(f"VIX: {vix:.1f}" if isinstance(vix, (int, float)) else "VIX: N/A")
        desc.append(f"Put/Call: {pcr:.2f}" if pcr is not None else "Put/Call: N/A")
        desc.append(f"Breadth: {breadth:.0f}% advancers" if breadth is not None else "Breadth: N/A")
        embed = discord.Embed(
            title=f"Market Mood – {ts}",
            description=" | ".join(desc[:2]) + "\n" + " | ".join(desc[2:]),
            colour=0x2ecc71 if (sp_pct or 0) >= 0 else 0xe74c3c,
        )
        if trending:
            embed.add_field(name="Trending tickers", value=", ".join(trending[:2]), inline=False)
        embed.set_footer(text="Data: Yahoo Finance · CBOE · Finviz – not financial advice")
        await itx.followup.send(embed=embed, ephemeral=ephemeral)

    @app_commands.command(name="marketbet", description="Place a weekly bull/bear bet or set reminder")
    @app_commands.describe(direction="bullish or bearish", reminder="Enable DM reminder on Monday")
    async def marketbet(self, itx: discord.Interaction, direction: Optional[Literal["bullish", "bearish"]] = None, reminder: Optional[bool] = None):
        log.info("/marketbet invoked by %s in %s", itx.user.id, chan_name(itx.channel))
        await itx.response.defer(thinking=True, ephemeral=True)
        now = datetime.now(NY_TZ)
        week = _week_start(now).date().isoformat()
        messages = []
        if direction:
            day_index = min(now.weekday(), 4)
            weight = int((5 - day_index) / 5 * 100)
            placed = self._place_bet(itx.user.id, week, direction, weight)
            if placed:
                messages.append(
                    f"{itx.user.mention}, your **{direction.title()}** bet for *Week of {week}* is locked!\nWeight: **{weight} pts** (placed on {now:%A})\nResults announced Friday 1 pm."
                )
            else:
                messages.append("You already placed a bet this week.")
        if reminder is not None:
            self._toggle_reminder(itx.user.id, reminder)
            state = "enabled" if reminder else "disabled"
            messages.append(f"DM reminder {state}.")
        if not messages:
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
        monday_open, friday_close = await self._week_open_close()
        if monday_open is None or friday_close is None:
            return
        pct = (friday_close - monday_open) / monday_open * 100
        outcome = "bullish" if pct >= 0 else "bearish"
        winners, board = self._record_scores(week, outcome)
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
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT user FROM bets WHERE week=?", (week,))
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


async def setup(bot: commands.Bot):
    await bot.add_cog(MarketsCog(bot))
