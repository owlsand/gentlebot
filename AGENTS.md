# Gentlebot Repository Guide

## Purpose
This document tells automated coding agents (Codex, Copilot-CI, GPT scripts, etc.) how to interact with Gentlebot's repo without breaking things.

### 1. Project overview
Gentlebot is a Discord bot packaged under `src/gentlebot`. It is Dockerized, uses Postgres for logging and is tested with Pytest.

### 2. Key invariants to **NEVER** violate
* **Entry-point** is `python -m gentlebot`
* **Line endings** are LF; `.gitattributes` enforces this
* **Formatting**: run `pre-commit` (Black + Ruff) before committing

### 3. Approved dependency layers

| Layer       | Package manager    | Notes                                                |
| ----------- | ------------------ | ---------------------------------------------------- |
| Python deps | `requirements.txt` | Edit this file; don't install ad-hoc in Dockerfile   |
| OS deps     | `apt-get`          | Must be added in Dockerfile after base image comment |
| Pyproject   | Not used yet       | Don't introduce Poetry without discussion            |

### 4. Allowed container edits
* **Startup script** lives in `scripts/start.sh`.
  * Wait-loop uses `pg_isready`; keep that dependency installed.
  * Migrations via `alembic upgrade head`.
  * Image prune behind `DOCKER_PRUNE` flag.
* If adding new startup hooks, extend *this* script—do not create a second entrypoint.

---

### 5. Running the bot
1. Create a virtual environment and install the libraries listed in `requirements.txt`.
2. Create a `.env` file containing `DISCORD_TOKEN` and other IDs (see `bot_config.py`).
3. During development run `python -m gentlebot` (or use `watchfiles` for auto-reload). For production set `BOT_ENV=PROD` or start the container.

### 6. Adding new features
- Write each feature as a `commands.Cog` subclass in a new file ending with `_cog.py` under `cogs/`.
- The bot automatically loads all cogs on startup.
- Keep Discord responses under 1900 characters and use async functions.
- Include a short docstring explaining any new commands.

### 7. Interacting with APIs
- API tokens and IDs are read from `.env` variables. Never commit actual tokens.
- The Hugging Face cogs require `HF_API_TOKEN` and optionally `HF_API_TOKEN_ALT` for billing fallback; other cogs may use public APIs.

### 8. Testing & CI rules
Before committing run:
```
pip install -r requirements.txt
python -m pytest -q
python test_harness.py
```
To simulate a Discord connection without starting the bot, run `BOT_OFFLINE=1 python test_harness.py`.

* Every new file must be covered by **at least one** test in `tests/`.
* Add a CI smoke step when you touch Docker or startup scripts.
* Don't disable existing Ruff/Black checks.

### 9. Coding style
- Follow PEP8 with four-space indents and type hints where practical.
- Keep new `cogs/` files suffixed with `_cog.py` and include a short docstring for commands.

### 10. Pull requests
- Summarize changes and include test results in the PR body.
- Do not commit `.env` or other secrets.

#### Documentation checklist
1. **What changed, in plain English.**
2. Why it doesn't break invariants above.
3. Manual test commands you ran (`docker compose up`, `/help` output, etc.).
