# Repository Guide

Gentlebot is a modular Discord bot built with **discord.py** v2. Each feature lives in a separate _cog_ under the `cogs/` folder. The bot integrates with third‑party APIs such as Hugging Face and Yahoo Finance.

## Running the bot
1. Create a virtual environment and install the libraries listed in the README.
2. Create a `.env` file containing `DISCORD_TOKEN` and other IDs (see `bot_config.py`).
3. Use `./dev_run.sh` during development for auto‑restart when files change. For production use `./run_bot.sh` or run `python main.py` with `env=PROD`.

## Adding new features
- Write each feature as a `commands.Cog` subclass in a new file ending with `_cog.py` under `cogs/`.
- The bot automatically loads all cogs on startup.
- Keep Discord responses under 1900 characters and use async functions.
- Include a short docstring explaining any new commands.

## Interacting with APIs
 - API tokens and IDs are read from `.env` variables. Never commit actual tokens.
 - The Hugging Face cogs require `HF_API_TOKEN` and optionally `HF_API_TOKEN_ALT` for billing fallback; other cogs may use public APIs.

No automated test suite is present. Run `./dev_run.sh` and interact with the bot in a test guild to verify changes.
