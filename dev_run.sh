#!/usr/bin/env bash
set -e
# dev_run.sh — auto-restarting bot for development
# Requires: `watchdog` or `watchfiles` installed in your environment

cd "$(dirname "$0")"

# Activate virtual environment if present
if [[ -f "venv/bin/activate" ]]; then
    source venv/bin/activate
fi

# Ensure the bot loads the TEST config
export env=TEST
export BOT_ENV=TEST

cmd="python main.py"

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

