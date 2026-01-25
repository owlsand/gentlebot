"""
MarketCog – stock charts with polished styling.
================================================
Provides advanced chart commands for stock tickers.

Slash commands shipped
----------------------
``/stock``     – fancy chart + key stats, supports ``1d`` · ``1w`` · ``1mo`` · ``3mo`` · ``6mo`` · ``ytd`` · ``1y`` · ``2y`` · ``5y`` · ``10y``

All IDs, tokens, and embed colours live in **bot_config.py**.
Requires: discord.py v2+, yfinance, matplotlib, pandas, python-dateutil,
requests.
"""

from __future__ import annotations

import io
from datetime import time
from typing import Tuple
import logging

import discord
from discord import app_commands
from discord.ext import commands
from ..util import chan_name, user_name
import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pytz
import yfinance as yf
import pandas as pd

from .. import bot_config as cfg

# Use a hierarchical logger so messages propagate to the main gentlebot logger
log = logging.getLogger(f"gentlebot.{__name__}")

# ── ENV -------------------------------------------------------------------
NY = pytz.timezone("America/New_York")


# ─────────────────────────────────────────────────────────────────────────────
class MarketCog(commands.Cog):
    """Stock-market slash commands with polished charts."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

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
                val = f"{val:,.2f}" if key != "marketCap" else f"{val/1e9:,.1f} B"
            lines.append(f"**{label}:** {val}")

        embed = discord.Embed(title=f"{symbol} Snapshot", colour=0x2081C3, description="\n".join(lines))
        embed.set_image(url=f"attachment://{symbol}.png")
        await itx.followup.send(embed=embed, file=file)


# ─── Loader ────────────────────────────────────────────────────────────────
async def setup(bot: commands.Bot):
    await bot.add_cog(MarketCog(bot))
