#!/usr/bin/env bash
set -e
# dev_run.sh — auto-restarting bot for development
# Uses `watchfiles` or `watchdog` for autoreload (both installed via requirements)

cd "$(dirname "$0")"

# parse optional --offline flag or BOT_OFFLINE env var
OFFLINE=0
if [[ "$1" == "--offline" ]]; then
    OFFLINE=1
    shift
fi
if [[ "${BOT_OFFLINE:-0}" == "1" ]]; then
    OFFLINE=1
fi

# Load environment variables from .env if present
if [[ -f ".env" ]]; then
    set -a
    source .env
    set +a
fi

# Activate virtual environment if present
if [[ -f "venv/bin/activate" ]]; then
    source venv/bin/activate
fi

if [[ "$OFFLINE" == "1" ]]; then
    echo "Running in offline mode: loading cogs only" >&2
    python test_harness.py
    exit 0
fi

# Ensure the bot loads the TEST config
export env=TEST
export BOT_ENV=TEST


# Verify that a token is available; otherwise notify the user and exit
if [[ -z "$DISCORD_TOKEN" ]]; then
    echo "DISCORD_TOKEN not set. Create a .env file or export the token before running." >&2
    exit 1
fi

# Ensure discord.py is available before attempting to run
if ! python -c "import discord" >/dev/null 2>&1; then
    echo "discord.py is missing. Run 'pip install -r requirements.txt' first." >&2
    exit 1
fi

export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}src"
cmd="python -m gentlebot"

if command -v watchmedo >/dev/null 2>&1; then
    watchmedo auto-restart \
        --patterns="*.py;*.json" \
        --ignore-patterns="*__pycache__*" \
        --recursive \
        -- bash -c "$cmd"
elif command -v watchfiles >/dev/null 2>&1; then
    watchfiles "$cmd"
else
    echo "watchmedo or watchfiles not installed; running without autoreload." >&2
    exec $cmd
fi

