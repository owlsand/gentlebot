from __future__ import annotations
"""
F1Cog – Formula 1 schedule & standings for Gentlebot
===================================================
Fetches live schedule from a JSON API and shows upcoming sessions.
Also scrapes current driver & constructor standings from formula1.com.

Slash commands:
  • /nextf1      – Show the next F1 session preview
  • /f1standings – Show current driver & constructor standings (top 10)

Requires:
  • discord.py v2+
  • requests, dateparser, pytz, bs4
  • Bot_config with GUILD_ID
  • ENV var F1_SCHEDULE_URL (optional override)
"""
import os
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
import requests
import dateparser
import pytz
from bs4 import BeautifulSoup

import bot_config as cfg

# Local timezone for display (fallback to UTC)
LOCAL_TZ = pytz.timezone(os.getenv("LOCAL_TZ", "UTC"))

class F1Cog(commands.Cog):
    """Provides Formula 1 schedule and standings commands from live API."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def fetch_f1_schedule(self) -> list[dict]:
        """Fetch and parse F1 schedule sessions sorted by UTC time."""
        url = os.getenv("F1_SCHEDULE_URL", "https://f1calendar.com/api/calendar")
        try:
            resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            data = resp.json()
            sessions = []
            for race in data.get("races", []):
                round_name = race.get("name")
                location_name = race.get("location")
                slug = race.get("slug", "")
                round_num = race.get("round")
                for session_name, iso in race.get("sessions", {}).items():
                    dt_utc = dateparser.parse(iso).astimezone(pytz.UTC)
                    dt_local = dt_utc.astimezone(LOCAL_TZ)
                    sessions.append({
                        "round": round_name,
                        "slug": slug,
                        "session": session_name,
                        "utc": dt_utc,
                        "local": dt_local,
                        "location": location_name,
                        "round_num": round_num,
                    })
            return sorted(sessions, key=lambda s: s["utc"])
        except Exception:
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
        drivers = []
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
        constructors = []
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

    @app_commands.command(name="nextf1", description="Show the next F1 session preview")
    async def nextf1(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        now = datetime.now(timezone.utc)
        sessions = self.fetch_f1_schedule()
        next_sess = next((s for s in sessions if s["utc"] > now), None)
        if not next_sess:
            await interaction.followup.send("No upcoming sessions found.")
            return
        embed = discord.Embed(
            title=f"Next F1 Session: {next_sess['round']} - {next_sess['session'].capitalize()}",
            description=f"{next_sess['location']}",
            color=discord.Color.red()
        )
        embed.add_field(name="UTC", value=next_sess["utc"].strftime("%Y-%m-%d %H:%M UTC"), inline=True)
        embed.add_field(name="Local", value=next_sess["local"].strftime("%Y-%m-%d %H:%M %Z"), inline=True)
        embed.set_footer(text=f"Round {next_sess['round_num']} | {next_sess['slug']}")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="f1standings", description="Show current F1 driver & constructor standings")
    async def f1standings(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        drivers, constructors = self.fetch_f1_standings()
        if not drivers and not constructors:
            await interaction.followup.send("Could not fetch standings at this time.")
            return
        embed = discord.Embed(title="F1 Standings", color=discord.Color.green())
        # Drivers
        driver_lines = [f"{d['pos']}. {d['name']} — {d['pts']} pts" for d in drivers]
        embed.add_field(name="Top 10 Drivers", value="\n".join(driver_lines), inline=False)
        # Constructors
        constructor_lines = [f"{c['pos']}. {c['team']} — {c['pts']} pts" for c in constructors]
        embed.add_field(name="Top 10 Constructors", value="\n".join(constructor_lines), inline=False)
        await interaction.followup.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(F1Cog(bot))









# import os
# from dotenv import load_dotenv
# load_dotenv()
# import sys
# import discord
# import json
# from discord.ext import commands, tasks
# from discord import app_commands
# from bs4 import BeautifulSoup
# import requests
# from dateutil import parser as dateparser, tz
# from datetime import datetime, timedelta
# import pytz

# # Timezone setup
# tz_local = tz.gettz(os.getenv('LOCAL_TZ', 'UTC'))
# intents = discord.Intents.default()
# intents.message_content = True
# bot = commands.Bot(command_prefix='/', intents=intents)

# # Configuration from env
# TOKEN = os.getenv('DISCORD_TOKEN')
# if not TOKEN:
#     sys.exit("Error: Bot access token is not set.")
# GUILD_ID = os.getenv('DISCORD_GUILD_ID')
# GUILD = discord.Object(id=int(GUILD_ID)) if GUILD_ID else None
# CHANNEL_ID = os.getenv('F1_DISCORD_CHANNEL_ID')
# NOTIFY_MINUTES = int(os.getenv('F1_NOTIFY_MINUTES', '30'))
# SCHEDULE_URL = os.getenv('F1_SCHEDULE_URL', 'https://f1calendar.com/api/calendar')
# REMINDER_SESSIONS = {'Sprint Qualifying', 'Sprint', 'Qualifying', 'Race'}

# # In-memory data
# schedule = []
# notified = set()

# def fetch_f1_schedule():
#     SCHEDULE_URL = os.getenv('F1_SCHEDULE_URL', 'https://f1calendar.com/api/calendar')
#     try:
#         resp = requests.get(SCHEDULE_URL, headers={'User-Agent': 'Mozilla/5.0'})
#         resp.raise_for_status()
#         data = resp.json()
#         sessions = []
#         for race in data.get('races', []):
#             round_name = race.get('name')  # e.g. 'Chinese Grand Prix'
#             location_name = race.get('location')
#             slug = race.get('slug', '')
#             round_num = race.get('round')
#             for session_name, iso in race.get('sessions', {}).items():
#                 dt_utc = dateparser.isoparse(iso).astimezone(pytz.UTC)
#                 dt_local = dt_utc.astimezone(tz_local)
#                 sessions.append({
#                     'round': round_name,
#                     'slug': slug,
#                     'session': session_name,
#                     'utc': dt_utc,
#                     'local': dt_local,
#                     'key': session_name,
#                     'location': location_name,
#                     'round_num': round_num
#                 })
#         return sorted(sessions, key=lambda s: s['utc'])
#     except:
#         return []

# # Fetch standings from official site
# def fetch_f1_standings():
#     year = datetime.now().year
#     base = 'https://www.formula1.com'
#     # Driver standings
#     d_url = f'{base}/en/results/{year}/drivers'
#     resp_d = requests.get(d_url, headers={'User-Agent': 'Mozilla/5.0'})
#     resp_d.raise_for_status()
#     soup_d = BeautifulSoup(resp_d.text, 'html.parser')
#     table_d = soup_d.find('table', class_='f1-table')
#     drivers = []
#     if table_d and table_d.tbody:
#         rows = table_d.tbody.find_all('tr')[:10]
#         for row in rows:
#             cells = row.find_all('td')
#             if len(cells) >= 5:
#                 pos = cells[0].get_text(strip=True)
#                 link = cells[1].find('a')
#                 name_raw = link.get_text(' ', strip=True) if link else cells[1].get_text(strip=True)
#                 # strip trailing 3-letter acronym if present
#                 parts = name_raw.split()
#                 if parts and len(parts[-1]) == 3 and parts[-1].isalpha():
#                     parts = parts[:-1]
#                 name = ' '.join(parts)
#                 pts = cells[-1].get_text(strip=True)
#                 drivers.append({'pos': pos, 'name': name, 'pts': pts})
#     # Constructor standings
#     t_url = f'{base}/en/results/{year}/team'
#     resp_t = requests.get(t_url, headers={'User-Agent': 'Mozilla/5.0'})
#     resp_t.raise_for_status()
#     soup_t = BeautifulSoup(resp_t.text, 'html.parser')
#     table_t = soup_t.find('table', class_='f1-table-with-data') or soup_t.find('table', class_='f1-table')
#     constructors = []
#     if table_t and table_t.tbody:
#         rows = table_t.tbody.find_all('tr')[:10]
#         for row in rows:
#             cells = row.find_all('td')
#             if len(cells) >= 3:
#                 pos = cells[0].get_text(strip=True)
#                 link = cells[1].find('a')
#                 team = link.get_text(' ', strip=True) if link else cells[1].get_text(strip=True)
#                 pts = cells[2].get_text(strip=True)
#                 constructors.append({'pos': pos, 'team': team, 'pts': pts})
#     return drivers, constructors

# # Helpers
# def get_upcoming_weekend():
#     now = datetime.now(pytz.UTC)
#     for s in schedule:
#         if s['utc'] > now:
#             next_round = s['round']
#             # Return all sessions for that round, in chronological order
#             return [x for x in schedule if x['round'] == next_round]
#     return []

# def get_upcoming_sessions_window(minutes):
#     now = datetime.now(pytz.UTC)
#     window = now + timedelta(minutes=minutes)
#     to_notify = []
#     for s in schedule:
#         key = (s['round'], s['session'], s['utc'])
#         if now < s['utc'] <= window and key not in notified and s['session'] in REMINDER_SESSIONS:
#             notified.add(key)
#             to_notify.append(s)
#     return to_notify

# SESSION_EMOJI = {
#     'Free Practice 1': '🔧',
#     'Free Practice 2': '🔧',
#     'Free Practice 3': '🔧',
#     'Sprint Qualifying': '⚡',
#     'Sprint': '💨',
#     'Qualifying': '🏁',
#     'Grand Prix': '🏆'
# }

# # Embed builder
# def build_preview_embed(weekend, embed_type):
#     round_name = weekend[0]['round']
#     location = weekend[0]['location']
#     gp = next((s for s in weekend if s['session'] == 'Grand Prix'), None)
#     # Choose prefix based on caller
#     if embed_type == 'notification':
#         title_base = f"Upcoming Race: {round_name}"
#     else:
#         title_base = f"Next F1 Race: {round_name}"
#     # Attach GP time
#     if gp:
#         gp_time = gp['local'].strftime('%a, %B %d').replace(' 0', ' ')
#         title = f"{title_base} ({gp_time})"
#     else:
#         title = title_base
#     slug = weekend[0].get('slug', '')
#     embed = discord.Embed(title=title, color=discord.Color.blue())
#     embed.add_field(name="Race Location 🗺️", value=location or "", inline=False)

#     if slug:
#         wiki_slug = slug.replace('-', ' ').title().replace(' ', '_')
#         wiki_url = f"https://en.wikipedia.org/wiki/{wiki_slug}"
#         try:
#             wresp = requests.get(wiki_url, headers={'User-Agent': 'Mozilla/5.0'})
#             wresp.raise_for_status()
#             wsoup = BeautifulSoup(wresp.text, 'html.parser')
#             # Select the track map from the infobox-image cell
#             cell = wsoup.find('td', class_='infobox-image')
#             if cell:
#                 img = cell.find('img')
#                 if img and img.has_attr('src'):
#                     src = img['src']
#                     if src.startswith('//'):
#                         src = 'https:' + src
#                     embed.set_image(url=src)
#         except Exception as e:
#             print(f"Track image error: {e}")

#     for s in weekend:
#         emoji = SESSION_EMOJI.get(s['session'], '')
#         local_str = s['local'].strftime('%A, %B %d, %I:%M%p').replace(' 0', ' ')
#         embed.add_field(name=f"{s['session']} {emoji}", value=f"{local_str}", inline=False)
#     embed.set_footer(text=f"Last updated: {datetime.now(tz_local).strftime('%A, %B %d, %I:%M%p').replace(' 0',' ')}")
#     return embed

# # Events
# @bot.event
# async def on_ready():
#     global schedule
#     schedule = fetch_f1_schedule()
#     if GUILD:
#         await bot.tree.sync(guild=GUILD)
#     else:
#         await bot.tree.sync()
#     if not daily_preview.is_running():
#         daily_preview.start()
#     if not reminder_loop.is_running():
#         reminder_loop.start()

# # Tasks
# @tasks.loop(hours=24)
# # Post race weekend preview on Thursdays
# async def daily_preview():
#     global schedule
#     schedule = fetch_f1_schedule()
#     now_local = datetime.now(tz_local)
#     if now_local.weekday() == 3:
#         weekend = get_upcoming_weekend()
#         if weekend:
#             embed = build_preview_embed(weekend, 'notification')
#             ch = bot.get_channel(CHANNEL_ID)
#             if ch:
#                 await ch.send(embed=embed)

# @tasks.loop(minutes=1)
# #Send session reminders ahead of time
# async def reminder_loop():
#     to_notify = get_upcoming_sessions_window(NOTIFY_MINUTES)
#     channel = bot.get_channel(CHANNEL_ID)
#     for s in to_notify:
#         if channel:
#             await ch.send(f"⏰ **{s['session']}** for **{s['round']}** starts in {NOTIFY_MINUTES} min\nLocal: {s['local'].strftime('%Y-%m-%d %H:%M %Z')}")

# # Commands
# @bot.tree.command(name='nextf1', description='Show next race weekend preview', guild=GUILD)
# async def slash_nextf1(interaction: discord.Interaction):
#     wk = get_upcoming_weekend()
#     if not wk: return await interaction.response.send_message('No upcoming race.', ephemeral=True)
#     await interaction.response.send_message(embed=build_preview_embed(wk,'request'))

# @bot.tree.command(name='f1standings', description='Show current Drivers and Constructors standings', guild=GUILD)
# async def slash_f1standings(interaction: discord.Interaction):
#     try:
#         drivers, constructors = fetch_f1_standings()
#         embed = discord.Embed(title='Current F1 Standings', color=discord.Color.gold())
#         # Driver's Championship section
#         pos_d = '\n'.join(d['pos'] for d in drivers)
#         name_d = '\n'.join(d['name'] for d in drivers)
#         pts_d = '\n'.join(f"{d['pts']} pts" for d in drivers)
#         embed.add_field(name='Pos', value=pos_d, inline=True)
#         embed.add_field(name='Driver', value=name_d, inline=True)
#         embed.add_field(name='Pts', value=pts_d, inline=True)
#         # Constructor's Championship section    
#         pos_c = '\n'.join(c['pos'] for c in constructors)
#         team_c = '\n'.join(c['team'] for c in constructors)
#         pts_c = '\n'.join(f"{c['pts']} pts" for c in constructors)
#         embed.add_field(name='Pos', value=pos_c, inline=True)
#         embed.add_field(name='Constructor', value=team_c, inline=True)
#         embed.add_field(name='Pts', value=pts_c, inline=True)
#         embed.set_footer(text=f"Last updated: {datetime.now(tz_local).strftime('%A, %B %d, %I:%M%p').replace(' 0',' ')}")
#         await interaction.response.send_message(embed=embed)
#     except Exception as e:
#         await interaction.response.send_message(f"Error fetching standings: {e}", ephemeral=True)

# # Run the bot
# bot.run(TOKEN)
