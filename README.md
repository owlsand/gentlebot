# Gentlebot
Gentlebot is a modular Discord bot composed of several **cogs** that handle different features.  It uses `discord.py` v2 and integrates with third‑party APIs such as Hugging Face and Yahoo Finance.

## Features
- **SportsCog** – `/nextf1` and `/f1standings` plus `/bigdumper` for Mariners stats.
- **MarketCog** – `/stock`, `/earnings`, `/marketmood` and `/marketbet` combine charts with a weekly bull/bear game.
**RolesCog** – Manages vanity reaction roles and activity-based roles. Roles are
  refreshed automatically on startup so redeployments keep badges up to date.
  Admins can still run `/refreshroles` to fetch 14 days of history and refresh
  roles manually. Ensure the bot's role is above these vanity roles and has the
  **Manage Roles** permission so it can assign and remove them.
- **PromptCog** – Posts a daily prompt generated via the Hugging Face API.
  Categories rotate randomly without repeating recent types, and the
  rotation state persists in `prompt_state.json` so redeployments keep
  things fresh.
- **HuggingFaceCog** – Adds AI conversation and emoji reactions using Hugging Face models.
- **StatsCog** – `/engagement` now replies "Working on it..." and then gathers
  unlimited history in the background before posting the stats and optional
  activity chart.
- **VersionCog** – `/version` prints the current commit hash for debugging.

## Repository Layout
```
src/gentlebot/__main__.py # package entry point
bot_config.py      # environment configuration and ID constants
cogs/               # feature cogs
  sports_cog.py     # F1 and baseball commands
  market_cog.py     # market commands and weekly game
  prompt_cog.py     # daily prompts
  huggingface_cog.py # conversation + emoji reactions
  stats_cog.py      # engagement statistics
run_bot.sh         # run helper (prod)
dev_run.sh         # auto-restart helper (dev)
setup.sh           # install dependencies and create the venv
```

## Setup
1. Install Python 3.10 or newer.
2. Run `./setup.sh` to create a virtual environment and install the required packages.  You can re-run it at any time to ensure everything is up to date.
3. Create a `.env` file with your bot token and other IDs (see `bot_config.py` for variables).  Example:
   ```ini
   DISCORD_TOKEN=<your bot token>
   DISCORD_APPLICATION_ID=<app id>
   DISCORD_GUILD_ID=<guild id>
    ALPHA_VANTAGE_KEY=<alpha vantage api key>
   MONEY_TALK_CHANNEL=<market channel id>
   HF_API_TOKEN=<hugging face token>
   # optional fallback if the primary token hits a billing error
   HF_API_TOKEN_ALT=<secondary hugging face token>
   # optional Postgres credentials for logging
   PG_USER=gentlebot
   PG_PASSWORD=<pg_password>
   PG_DB=gentlebot
   # enable message archival tables
   ARCHIVE_MESSAGES=1
   # or provide an explicit async connection URL
   DATABASE_URL=postgresql+asyncpg://gentlebot:<pg_password>@db:5432/gentlebot
   # PostgresHandler converts this to ``postgresql://`` when using ``asyncpg``
   ```
4. If using Postgres logging, run the Alembic migration to create the
   `bot_logs` table. Database logging only stores **INFO** and above so
   verbose debug messages remain in the console or log file:
   ```bash
   alembic upgrade head
   ```
   The migrations create tables in the `discord` schema. Connections should
   use `SET search_path=discord,public` as done by the bot's database helpers.
5. Set `ARCHIVE_MESSAGES=1` to enable message archival. The archive cog
   records all existing guilds and channels on startup and then logs new
   messages and reactions. Run the migration again to create the tables
   used by the archive cog.
   ```bash
   alembic upgrade head
   ```
7. Optionally backfill up to 90 days of history before starting the bot:
   ```bash
   python backfill_archive.py --days 90
   ```
   The script may be re-run; inserts use `ON CONFLICT DO NOTHING` so no
   duplicates are created.
8. Run the bot:
   ```bash
   ./run_bot.sh
   # or manually via Python
   python -m gentlebot
   ```
During development you can use `./dev_run.sh` for automatic restarts when files change. The `watchfiles` and `watchdog` packages are installed from `requirements.txt`, so autoreload works out of the box. Logs are written to `logs/bot.log` unless a Postgres connection is configured, in which case they are archived to the `bot_logs` table instead.
Pass `--offline` to `dev_run.sh` (or set `BOT_OFFLINE=1`) to run the bundled `test_harness.py` instead, which loads all cogs without connecting to Discord.

## Docker
You can also run the bot inside a container on a Raspberry Pi. A `Dockerfile`
is provided. Build the image and pass your `.env` file at runtime. The container
entrypoint waits for Postgres to accept connections, runs `alembic upgrade head`
and prunes dangling images before launching the bot:

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

The container sets `LOG_LEVEL=INFO` so console output is less verbose by default.

## Notes
- `BOT_ENV` controls whether `bot_config.py` loads **TEST** or **PROD** IDs.
 - The Hugging Face cogs require an API key in `HF_API_TOKEN` and optionally `HF_MODEL`.
   You can provide a backup key in `HF_API_TOKEN_ALT` which will be used if the
   primary token hits a billing error.
 - Set `DATABASE_URL` (or PG_* creds) to enable writing bot logs to a Postgres database.

## Contributing
Each cog is self-contained. Add a new `*_cog.py` file under `cogs/` and it will be loaded automatically.
