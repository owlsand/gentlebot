# Gentlebot

Gentlebot is a modular Discord bot composed of several **cogs** that handle different features.  It uses `discord.py` v2 and integrates with third‑party APIs such as Hugging Face and Yahoo Finance.

## Features

- **F1Cog** – `/nextf1` and `/f1standings` commands show upcoming Formula 1 sessions and current standings.
- **MarketCog** – `/stock` renders stock charts with Matplotlib and `/earnings` shows the next earnings date.
- **RolesCog** – Manages vanity reaction roles and activity‑based roles.
- **PromptCog** – Posts a daily prompt generated via the Hugging Face API.
- **HuggingFaceCog** – Adds AI conversation and emoji reactions using Hugging Face models.
- **StatsCog** – `/engagement` shows top members/channels and optional activity chart.

## Repository Layout

```
main.py            # bot entry point
bot_config.py      # environment configuration and ID constants
cogs/               # feature cogs
  f1_cog.py         # Formula 1 commands
  market_cog.py     # stock/earnings commands
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
   pip install discord.py requests python-dateutil pytz beautifulsoup4 \
       yfinance matplotlib pandas huggingface-hub watchdog
   ```
4. Create a `.env` file with your bot token and other IDs (see `bot_config.py` for variables).  Example:
   ```ini
   DISCORD_TOKEN=<your bot token>
   DISCORD_APPLICATION_ID=<app id>
   DISCORD_GUILD_ID=<guild id>
   ```
5. Run the bot:
   ```bash
   ./run_bot.sh
   ```
During development you can use `./dev_run.sh` for automatic restarts when files change (requires `watchdog`).

## Production Tips

Logs are written to `bot.log` with rotation so they don't grow indefinitely.
When deploying permanently, consider running the bot under a process manager
like **systemd** so it restarts automatically on failure. A minimal service
unit might look like:

```ini
[Service]
WorkingDirectory=/path/to/gentlebot
ExecStart=/path/to/gentlebot/venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

On a Raspberry Pi 5 install common build prerequisites before `pip install`:

```bash
sudo apt update
sudo apt install python3-dev build-essential libatlas-base-dev libffi-dev \
    libssl-dev libjpeg-dev libopenjp2-7 libtiff5
```

## Notes

- `BOT_ENV` controls whether `bot_config.py` loads **TEST** or **PROD** IDs.
- The Hugging Face cogs require an API key in `HF_API_TOKEN` and optionally `HF_MODEL`.
## Contributing

Each cog is self-contained. Add a new `*_cog.py` file under `cogs/` and it will be loaded automatically.
