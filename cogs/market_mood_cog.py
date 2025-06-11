"""
MarketMoodCog – daily macro sentiment summary
=============================================
Posts a single "Market Mood Ring" embed at U.S. market open and on demand.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time
from zoneinfo import ZoneInfo
from typing import Tuple, Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks
import requests
import feedparser

import bot_config as cfg
from util import chan_name

log = logging.getLogger(__name__)

ALPHA_URL = "https://www.alphavantage.co/query"
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
TECHMEME_RSS = "https://www.techmeme.com/feed.xml"
SEEKING_ALPHA_RSS = "https://seekingalpha.com/api/sa/combined/top-news.xml"

NY_TZ = ZoneInfo("US/Eastern")

class MarketMoodCog(commands.Cog):
    """Scheduled market sentiment embed and /moodnow command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = requests.Session()
        self.mood_task.start()

    def cog_unload(self):
        self.mood_task.cancel()
        self.session.close()

    # ─── Utils ──────────────────────────────────────────────────────────────
    async def _get_json(self, params: dict) -> dict:
        for _ in range(2):
            resp = await asyncio.to_thread(self.session.get, ALPHA_URL, params=params, timeout=10)
            if resp.status_code == 429:
                log.warning("Alpha Vantage rate limit hit. Retrying in 60s.")
                await asyncio.sleep(60)
                continue
            resp.raise_for_status()
            return resp.json()
        return {}

    async def _fetch_quote_change(self, symbol: str) -> Optional[float]:
        try:
            j = await self._get_json({"function": "GLOBAL_QUOTE", "symbol": symbol, "apikey": cfg.ALPHA_VANTAGE_KEY})
            quote = j.get("Global Quote", {})
            pct_str = quote.get("10. change percent")
            if pct_str:
                return float(pct_str.strip("%"))
            price = float(quote.get("05. price", 0))
            prev = float(quote.get("08. previous close", 0))
            if prev:
                return (price - prev) / prev * 100
        except Exception:
            log.exception("Failed to fetch change for %s", symbol)
        return None

    async def _fetch_quote_price(self, symbol: str) -> Optional[float]:
        try:
            j = await self._get_json(
                {
                    "function": "GLOBAL_QUOTE",
                    "symbol": symbol,
                    "apikey": cfg.ALPHA_VANTAGE_KEY,
                }
            )
            quote = j.get("Global Quote", {})
            price = quote.get("05. price")
            if price is not None:
                return float(price)
        except Exception:
            log.exception("Failed to fetch price for %s", symbol)
        return None

    async def _fetch_yield(self) -> Optional[float]:
        try:
            resp = await asyncio.to_thread(self.session.get, FRED_URL, params={"id": "DGS10"}, timeout=10)
            resp.raise_for_status()
            line = resp.text.strip().splitlines()[-1]
            return float(line.split(",")[1])
        except Exception:
            log.exception("Failed to fetch 10Y yield")
            return None

    async def _fetch_headline(self) -> Tuple[str, str]:
        try:
            feed = await asyncio.to_thread(feedparser.parse, TECHMEME_RSS)
            if feed.entries:
                e = feed.entries[0]
                return e.title, e.link
        except Exception:
            log.exception("Failed to fetch Techmeme RSS")
        return "N/A", "https://www.techmeme.com/"

    async def _fetch_sa_headline(self) -> Tuple[str, str]:
        try:
            feed = await asyncio.to_thread(feedparser.parse, SEEKING_ALPHA_RSS)
            if feed.entries:
                e = feed.entries[0]
                return e.title, e.link
        except Exception:
            log.exception("Failed to fetch Seeking Alpha RSS")
        return "N/A", "https://seekingalpha.com/"

    # ─── Mood Helpers ───────────────────────────────────────────────────────
    @staticmethod
    def classify(pct: float) -> Tuple[str, int]:
        if pct >= 0.5:
            return "🟢", 0x2ECC71
        if pct >= 0.0:
            return "🟩", 0x27AE60
        if pct >= -0.5:
            return "🟨", 0xF1C40F
        if pct >= -1.0:
            return "🟧", 0xE67E22
        return "🔴", 0xE74C3C

    async def build_embed(self) -> discord.Embed:
        pct, vix, ten_y, (headline, link), (sa_title, sa_link) = await asyncio.gather(
            self._fetch_quote_change("^GSPC"),
            self._fetch_quote_price("^VIX"),
            self._fetch_yield(),
            self._fetch_headline(),
            self._fetch_sa_headline(),
        )
        pct = pct if pct is not None else 0.0
        vix = vix if vix is not None else float("nan")
        ten_y = ten_y if ten_y is not None else float("nan")
        emoji, colour = self.classify(pct)
        desc = (
            f"{emoji}\n"
            f"\u2022 **S&P** {pct:+.2f}%\n"
            f"\u2022 **VIX** {vix:.1f}\n"
            f"\u2022 **10Y** {ten_y:.2f}%"
        )
        embed = discord.Embed(
            title="📈 Market Mood Ring",
            description=desc,
            colour=colour,
        )
        embed.add_field(name="Top Techmeme Story", value=f"[{headline}]({link})", inline=False)
        embed.add_field(name="Top Seeking Alpha Story", value=f"[{sa_title}]({sa_link})", inline=False)
        embed.set_footer(text="Data: Alpha Vantage · FRED · Techmeme · Seeking Alpha")
        return embed

    async def publish(self):
        channel = self.bot.get_channel(cfg.MONEY_TALK_CHANNEL)
        if not channel:
            log.error("Money Talk channel %s not found", cfg.MONEY_TALK_CHANNEL)
            return
        try:
            embed = await self.build_embed()
            await channel.send(embed=embed)
            log.info("Market mood posted to %s", chan_name(channel))
        except Exception:
            log.exception("Failed to post market mood")

    # ─── Scheduler ──────────────────────────────────────────────────────────
    @tasks.loop(time=time(9, 30, tzinfo=NY_TZ))
    async def mood_task(self):
        now = datetime.now(NY_TZ)
        if now.weekday() >= 5:  # Skip weekends
            return
        await self.publish()

    @mood_task.before_loop
    async def before_mood(self):
        await self.bot.wait_until_ready()

    # ─── Command ────────────────────────────────────────────────────────────
    @app_commands.command(name="moodnow", description="Post Market Mood Ring now")
    @commands.has_permissions(administrator=True)
    async def moodnow(self, itx: discord.Interaction):
        log.info("/moodnow invoked by %s in %s", itx.user.id, chan_name(itx.channel))
        await itx.response.defer(thinking=True)
        await self.publish()
        await itx.followup.send("Market mood posted.")

async def setup(bot: commands.Bot):
    await bot.add_cog(MarketMoodCog(bot))
