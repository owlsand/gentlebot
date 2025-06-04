"""
MarketCog – full‑fat stock & chart commands for Gentlebot
=======================================================
Refactor of the original `market_bot.py` into a discord.py **Cog** so it can
be loaded alongside the F1 and Role cogs.

Slash commands shipped
----------------------
/stock   – fancy chart + key stats, supports 1d · 1w · 1mo · 3mo · 6mo · ytd · 1y · 2y · 5y · 10y
/earnings – next earnings date

All IDs, tokens, and embed colours live in **bot_config.py**.
Requires: discord.py v2+, yfinance, matplotlib, pandas, python-dateutil.
"""

from __future__ import annotations

import io
from datetime import datetime, time, timedelta
from typing import Tuple
import logging

import discord
from discord import app_commands
from discord.ext import commands
import matplotlib
matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pytz
import yfinance as yf
import pandas as pd

import bot_config as cfg

log = logging.getLogger(__name__)

# ── ENV -------------------------------------------------------------------
TOKEN    = cfg.TOKEN
GUILD_ID = cfg.GUILD_ID
NY       = pytz.timezone("America/New_York")

# ─────────────────────────────────────────────────────────────────────────────
class MarketCog(commands.Cog):
    """Stock‑market slash commands with polished charts."""

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
            if val is None: continue
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
        await itx.response.defer()
        tk = yf.Ticker(symbol.upper())
        cal = tk.calendar
        if cal.empty or "Earnings Date" not in cal.index:
            await itx.followup.send("No upcoming earnings date found.")
            return
        date = cal.loc["Earnings Date"][0].to_pydatetime()
        await itx.followup.send(f"Next earnings call for **{symbol.upper()}**: **{date:%Y‑%m‑%d}**")

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
