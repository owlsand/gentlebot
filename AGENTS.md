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

## Tests
Before committing run the local checks below.  Install dependencies with
`pip install -r requirements.txt` first so modules import cleanly.

Run these commands to verify everything loads:
```
python -m pytest -q       # run unit tests in tests/
python test_harness.py    # ensure all cogs load offline
```
To simulate a Discord connection without starting the bot, run
`BOT_OFFLINE=1 ./dev_run.sh --offline` which executes the harness script.

## Coding style
- Follow PEP8 with four-space indents and type hints where practical.
- Keep new `cogs/` files suffixed with `_cog.py` and include a short docstring for commands.

## Pull requests
- Summarize changes and include test results in the PR body.
- Do not commit `.env` or other secrets.
