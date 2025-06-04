# Gentlebot

Gentlebot is a modular Discord bot composed of several **cogs** that handle different features.  It uses `discord.py` v2 and integrates with third‑party APIs such as Hugging Face and Yahoo Finance.

## Features

- **F1Cog** – `/nextf1` and `/f1standings` commands show upcoming Formula 1 sessions and current standings.
- **MarketCog** – `/stock` renders stock charts with Matplotlib and `/earnings` shows the next earnings date.
- **RolesCog** – Manages vanity reaction roles and activity‑based roles.
- **PromptCog** – Posts a daily prompt generated via the Hugging Face API.
- **HuggingFaceCog** – Adds AI conversation and emoji reactions using Hugging Face models.

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
run_bot.sh         # run helper (prod)
dev_run.sh         # auto-restart helper (dev)
check_commands.sh  # verify /stock command registration
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

## Notes

- `BOT_ENV` controls whether `bot_config.py` loads **TEST** or **PROD** IDs.
- The Hugging Face cogs require an API key in `HF_API_TOKEN` and optionally `HF_MODEL`.
- `check_commands.sh` is a helper to confirm that the `/stock` command is registered with Discord.

## Contributing

Each cog is self-contained. Add a new `*_cog.py` file under `cogs/` and it will be loaded automatically.
