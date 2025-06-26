# Gentlebot
Gentlebot is a modular Discord bot composed of several **cogs** that handle different features.  It uses `discord.py` v2 and integrates with third‑party APIs such as Hugging Face and Yahoo Finance.

## Features
- **F1Cog** – `/nextf1` and `/f1standings` commands show upcoming Formula 1 sessions and current standings.
- **MarketCog** – `/stock` renders stock charts with Matplotlib and `/earnings` shows the next earnings date.
- **MarketMoodCog** – *(disabled)* posts a daily "Market Mood Ring" with a Monday sentiment poll and Friday wrap-up.
- **RolesCog** – Manages vanity reaction roles and activity‑based roles.
- **PromptCog** – Posts a daily prompt generated via the Hugging Face API.
- **HuggingFaceCog** – Adds AI conversation and emoji reactions using Hugging Face models.
- **StatsCog** – `/engagement` now replies "Working on it..." and then gathers
  unlimited history in the background before posting the stats and optional
  activity chart.
- **VersionCog** – `/version` prints the current commit hash for debugging.

## Repository Layout
```
main.py            # bot entry point
bot_config.py      # environment configuration and ID constants
cogs/               # feature cogs
  f1_cog.py         # Formula 1 commands
  market_cog.py     # stock/earnings commands
  market_mood_cog.py # daily market sentiment
  roles_cog.py      # role automation
  prompt_cog.py     # daily prompts
  huggingface_cog.py # conversation + emoji reactions
  stats_cog.py      # engagement statistics
run_bot.sh         # run helper (prod)
dev_run.sh         # auto-restart helper (dev)
```

## Setup
1. Install Python 3.10 or newer.
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   pip install python-dateutil pytz beautifulsoup4 yfinance matplotlib pandas \
       timezonefinder huggingface-hub watchdog
   ```
4. Create a `.env` file with your bot token and other IDs (see `bot_config.py` for variables).  Example:
   ```ini
   DISCORD_TOKEN=<your bot token>
   DISCORD_APPLICATION_ID=<app id>
   DISCORD_GUILD_ID=<guild id>
    ALPHA_VANTAGE_KEY=<alpha vantage api key>
   MONEY_TALK_CHANNEL=<market mood channel id>
   ENABLE_MARKET_MOOD=1  # set to 1 to enable the Market Mood Ring
   HF_API_TOKEN=<hugging face token>
   # optional fallback if the primary token hits a billing error
   HF_API_TOKEN_ALT=<secondary hugging face token>
   ```
5. Run the bot:
   ```bash
   ./run_bot.sh
   ```
During development you can use `./dev_run.sh` for automatic restarts when files change (requires `watchdog`).
For a quick offline sanity check you can run `python test_harness.py` which loads all cogs without connecting to Discord.

## Docker
You can also run the bot inside a container on a Raspberry Pi. A `Dockerfile`
is provided. Build the image and pass your `.env` file at runtime:

```bash
docker build -t gentlebot .
docker run --env-file .env --rm gentlebot
```

### GitHub Actions
A workflow in `.github/workflows/docker-image.yml` automatically builds and
pushes a multi-architecture image to **GitHub Container Registry** whenever the
`main` branch is updated. The image is tagged with `latest` and the commit SHA.
You can pull and run the prebuilt container instead of building locally:

```bash
docker pull ghcr.io/<owner>/<repo>:latest
docker run --env-file .env --rm ghcr.io/<owner>/<repo>:latest
```

## Notes
- `BOT_ENV` controls whether `bot_config.py` loads **TEST** or **PROD** IDs.
 - The Hugging Face cogs require an API key in `HF_API_TOKEN` and optionally `HF_MODEL`.
   You can provide a backup key in `HF_API_TOKEN_ALT` which will be used if the
   primary token hits a billing error.

## Contributing
Each cog is self-contained. Add a new `*_cog.py` file under `cogs/` and it will be loaded automatically.
