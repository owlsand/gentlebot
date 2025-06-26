"""
SportsCog - Formula 1 schedule & standings plus Mariners stats
================================================================
Slash commands:
  • /nextf1      - Show the next F1 race weekend preview with track map
  • /f1standings - Show current driver & constructor standings (top 10)
  • /bigdumper   - Show Cal Raleigh season stats and latest home run video

Requires:
  • discord.py v2+
  • requests, python-dateutil, pytz, bs4, timezonefinder
  • Bot_config with GUILD_ID
  • ENV var F1_SCHEDULE_URL (optional override)
"""

from __future__ import annotations
import os
from datetime import datetime, timezone, timedelta
import logging

import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from util import chan_name
import requests
from dateutil import parser
import pytz
from timezonefinder import TimezoneFinder
from bs4 import BeautifulSoup

# ── time zones --------------------------------------------------------------
import bot_config as cfg

log = logging.getLogger(__name__)

# Local timezone for display (fallback to UTC)
LOCAL_TZ = pytz.timezone(os.getenv("LOCAL_TZ", "UTC"))
# Pacific time for schedule comparison
PST_TZ = pytz.timezone("America/Los_Angeles")
# Finder for track locales
TF = TimezoneFinder()
# Map session names to emojis
SESSION_EMOJI = {
    "Free Practice 1": "🛠",
    "Free Practice 2": "🛠",
    "Free Practice 3": "🛠",
    "Qualifying": "🏁",
    "Grand Prix": "🏆",
}

# MLB constants
PLAYER_ID = 663728
TEAM_ID = 136

class SportsCog(commands.Cog):
    """Provides Formula 1 schedule & standings commands plus Mariners stats."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = requests.Session()

    def fetch_f1_schedule(self) -> list[dict]:
        """Fetch and parse F1 schedule sessions sorted by UTC time."""
        url = os.getenv("F1_SCHEDULE_URL", "https://f1calendar.com/api/calendar")
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            data = resp.json()
            sessions: list[dict] = []
            for race in data.get("races", []):
                round_name = race.get("name")
                location_name = race.get("location")
                slug = race.get("slug", "")
                round_num = race.get("round")
                lat = race.get("latitude")
                lon = race.get("longitude")
                race_tz_name = TF.timezone_at(lng=lon, lat=lat)
                race_tz = pytz.timezone(race_tz_name) if race_tz_name else pytz.UTC
                for session_name, iso in race.get("sessions", {}).items():
                    dt_utc = parser.isoparse(iso).astimezone(pytz.UTC)
                    dt_local = dt_utc.astimezone(race_tz)
                    dt_pst = dt_utc.astimezone(PST_TZ)
                    sessions.append({
                        "round": round_name,
                        "slug": slug,
                        "session": session_name,
                        "utc": dt_utc,
                        "pst": dt_pst,
                        "local": dt_local,
                        "location": location_name,
                        "round_num": round_num,
                    })
            return sorted(sessions, key=lambda s: s["utc"])
        except Exception as e:
            log.exception("Failed to fetch F1 schedule: %s", e)
            return []

    def fetch_f1_standings(self) -> tuple[list[dict], list[dict]]:
        """Scrape top 10 driver and constructor standings from formula1.com."""
        year = datetime.now().year
        base = 'https://www.formula1.com'
        headers = {'User-Agent': 'Mozilla/5.0'}
        # Driver standings
        d_url = f'{base}/en/results/{year}/drivers'
        resp_d = requests.get(d_url, headers=headers)
        resp_d.raise_for_status()
        soup_d = BeautifulSoup(resp_d.text, 'html.parser')
        table_d = soup_d.find('table', class_='f1-table')
        drivers: list[dict] = []
        if table_d and table_d.tbody:
            rows = table_d.tbody.find_all('tr')[:10]
            for row in rows:
                cells = row.find_all('td')
                pos = cells[0].get_text(strip=True)
                link = cells[1].find('a')
                name_raw = link.get_text(' ', strip=True) if link else cells[1].get_text(strip=True)
                parts = name_raw.split()
                if parts and len(parts[-1]) == 3 and parts[-1].isalpha():
                    parts = parts[:-1]
                name = ' '.join(parts)
                pts = cells[-1].get_text(strip=True)
                drivers.append({'pos': pos, 'name': name, 'pts': pts})
        # Constructor standings
        t_url = f'{base}/en/results/{year}/team'
        resp_t = requests.get(t_url, headers=headers)
        resp_t.raise_for_status()
        soup_t = BeautifulSoup(resp_t.text, 'html.parser')
        table_t = soup_t.find('table', class_='f1-table-with-data') or soup_t.find('table', class_='f1-table')
        constructors: list[dict] = []
        if table_t and table_t.tbody:
            rows = table_t.tbody.find_all('tr')[:10]
            for row in rows:
                cells = row.find_all('td')
                pos = cells[0].get_text(strip=True)
                link = cells[1].find('a')
                team = link.get_text(' ', strip=True) if link else cells[1].get_text(strip=True)
                pts = cells[2].get_text(strip=True)
                constructors.append({'pos': pos, 'team': team, 'pts': pts})
        return drivers, constructors

    def build_preview_embed(self, weekend: list[dict], embed_type: str = 'preview') -> discord.Embed:
        """Construct the embed for a given race weekend, including track map."""
        round_name = weekend[0]['round']
        location = weekend[0]['location']
        gp = next((s for s in weekend if 'race' in s['session'].lower()), None)
        # Title
        title_base = f"Next F1 Race: {round_name}" if embed_type != 'notification' else f"Upcoming Race: {round_name}"
        if gp:
            gp_time = gp['pst'].strftime('%a, %B %d').replace(' 0', ' ')
            title = f"{title_base} ({gp_time} PST)"
        else:
            title = title_base
        embed = discord.Embed(title=title, color=discord.Color.blue())
        embed.add_field(name="Race Location 🗺️", value=location or "", inline=False)
        # Track map via Wikipedia
        slug = weekend[0].get('slug', '')
        if slug:
            wiki_slug = slug.replace('-', ' ').title().replace(' ', '_')
            wiki_url = f"https://en.wikipedia.org/wiki/{wiki_slug}"
            try:
                wresp = requests.get(wiki_url, headers={'User-Agent': 'Mozilla/5.0'})
                wresp.raise_for_status()
                wsoup = BeautifulSoup(wresp.text, 'html.parser')
                cell = wsoup.find('td', class_='infobox-image')
                if cell:
                    img = cell.find('img')
                    if img and img.has_attr('src'):
                        src = img['src']
                        if src.startswith('//'):
                            src = 'https:' + src
                        embed.set_image(url=src)
            except Exception as e:
                log.exception("Failed to fetch track map: %s", e)
        # Session fields
        for s in weekend:
            # label + emoji
            lbl_key = s['session']
            if 'practice' in lbl_key.lower():
                num = ''.join(filter(str.isdigit, lbl_key)) or ''
                label = f"Free Practice {num}"
            elif 'qualifying' in lbl_key.lower():
                label = 'Qualifying'
            elif 'race' in lbl_key.lower():
                label = 'Grand Prix'
            else:
                label = lbl_key.capitalize()
            emoji = SESSION_EMOJI.get(label, '')
            pst_str = s['pst'].strftime('%A, %B %d, %I:%M%p').replace(' 0', ' ')
            loc_str = s['local'].strftime('%A, %B %d, %I:%M%p').replace(' 0', ' ')
            embed.add_field(
                name=f"{label} {emoji}",
                value=f"{pst_str} PST / {loc_str} local",
                inline=False,
            )
        # Footer
        updated_str = datetime.now(LOCAL_TZ).strftime('%A, %B %d, %I:%M%p').replace(' 0', ' ')
        embed.set_footer(text=f"Last updated: {updated_str}")
        return embed

    # --- Cal Raleigh helpers -------------------------------------------------
    def fetch_season_stats(self) -> dict:
        year = datetime.now().year
        url = f"https://statsapi.mlb.com/api/v1/people/{PLAYER_ID}/stats"
        params = {"stats": "season", "group": "hitting", "season": year}
        resp = self.session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return data["stats"][0]["splits"][0]["stat"]

    def find_last_homer(self) -> tuple[str, str, str]:
        today = datetime.now().date()
        for i in range(0, 180):  # look back up to ~6 months
            day = (today - timedelta(days=i)).strftime("%Y-%m-%d")
            params = {
                "hydrate": f"stats(group=hitting,type=byDateRange,startDate={day},endDate={day})"
            }
            try:
                resp = self.session.get(
                    f"https://statsapi.mlb.com/api/v1/people/{PLAYER_ID}",
                    params=params,
                    timeout=10,
                )
                stats = resp.json().get("people", [{}])[0].get("stats", [])
                if not stats or not stats[0]["splits"]:
                    continue
                hr = int(stats[0]["splits"][0]["stat"].get("homeRuns", 0))
                if hr < 1:
                    continue
                sched = self.session.get(
                    "https://statsapi.mlb.com/api/v1/schedule",
                    params={
                        "sportId": 1,
                        "teamId": TEAM_ID,
                        "startDate": day,
                        "endDate": day,
                    },
                    timeout=10,
                )
                game_pk = sched.json()["dates"][0]["games"][0]["gamePk"]
                content = self.session.get(
                    f"https://statsapi.mlb.com/api/v1/game/{game_pk}/content",
                    timeout=10,
                ).json()
                items = (
                    content.get("highlights", {})
                    .get("highlights", {})
                    .get("items", [])
                )
                for it in items:
                    headline = (it.get("headline") or "").lower()
                    if "raleigh" in headline and "home run" in headline:
                        video = it.get("playbacks", [{}])[0].get("url")
                        cuts = it.get("image", {}).get("cuts", [])
                        image = cuts[0].get("src") if cuts else ""
                        if video:
                            return day, video, image
                if items:
                    video = items[0].get("playbacks", [{}])[0].get("url", "")
                    cuts = items[0].get("image", {}).get("cuts", [])
                    image = cuts[0].get("src") if cuts else ""
                    return day, video, image
            except Exception as e:
                log.warning("Failed to fetch homer info for %s: %s", day, e)
        return "", "", ""

    # --- Cal Raleigh command -------------------------------------------------
    @app_commands.command(name="bigdumper", description="Cal Raleigh stats and latest homer")
    async def bigdumper(self, interaction: discord.Interaction):
        log.info("/bigdumper invoked by %s in %s", interaction.user.id, chan_name(interaction.channel))
        await interaction.response.defer(thinking=True)
        try:
            stats, hr_info = await asyncio.gather(
                asyncio.to_thread(self.fetch_season_stats),
                asyncio.to_thread(self.find_last_homer),
            )
        except Exception:
            log.exception("Failed to fetch Cal Raleigh info")
            await interaction.followup.send("Could not fetch data right now.")
            return

        if not stats:
            await interaction.followup.send("No stats available.")
            return
        avg = stats.get("avg", "N/A")
        obp = stats.get("obp", "N/A")
        slg = stats.get("slg", "N/A")
        ops = stats.get("ops", "N/A")
        hr = stats.get("homeRuns", "0")
        rbi = stats.get("rbi", "0")
        gp = stats.get("gamesPlayed", "0")
        ab = stats.get("atBats", "0")
        runs = stats.get("runs", "0")
        hits = stats.get("hits", "0")
        bb = stats.get("baseOnBalls", "0")
        so = stats.get("strikeOuts", "0")
        sb = stats.get("stolenBases", "0")
        lines = [
            f"**G:** {gp} **AB:** {ab} **R:** {runs} **H:** {hits}",
            f"**HR:** {hr} **RBI:** {rbi} **SB:** {sb}",
            f"**BB:** {bb} **SO:** {so}",
            f"**AVG:** {avg} **OBP:** {obp} **SLG:** {slg} **OPS:** {ops}",
        ]
        desc = "\n".join(lines)
        title_date = datetime.now().strftime("%b %d")
        embed = discord.Embed(
            title=f"Big Dumper Stats ({title_date})",
            description=desc,
            color=discord.Color.blue(),
        )
        date, video, image = hr_info
        if video:
            embed.add_field(name="Latest Home Run", value=f"{date} [Video]({video})", inline=False)
        if image:
            embed.set_image(url=image)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="nextf1", description="Show the next F1 race weekend preview with track map")
    async def nextf1(self, interaction: discord.Interaction):
        """Show embed for next race weekend."""
        log.info("/nextf1 invoked by %s in %s", interaction.user.id, chan_name(interaction.channel))
        await interaction.response.defer(thinking=True)
        now = datetime.now(timezone.utc)
        sessions = self.fetch_f1_schedule()
        upcoming = [s for s in sessions if s['utc'] > now]
        if not upcoming:
            await interaction.followup.send("No upcoming sessions found.")
            return
        # Extract weekend sessions
        next_round = upcoming[0]['round']
        weekend = [s for s in upcoming if s['round'] == next_round]
        embed = self.build_preview_embed(weekend, embed_type='preview')
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="f1standings", description="Show current F1 driver & constructor standings")
    async def f1standings(self, interaction: discord.Interaction):
        log.info("/f1standings invoked by %s in %s", interaction.user.id, chan_name(interaction.channel))
        await interaction.response.defer(thinking=True)
        drivers, constructors = self.fetch_f1_standings()
        if not drivers and not constructors:
            await interaction.followup.send("Could not fetch standings at this time.")
            return
        embed = discord.Embed(title="F1 Standings", color=discord.Color.green())
        driver_lines = [f"{d['pos']}. {d['name']} — {d['pts']} pts" for d in drivers]
        embed.add_field(name="Top 10 Drivers", value="\n".join(driver_lines), inline=False)
        constructor_lines = [f"{c['pos']}. {c['team']} — {c['pts']} pts" for c in constructors]
        embed.add_field(name="Top 10 Constructors", value="\n".join(constructor_lines), inline=False)
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(SportsCog(bot))
