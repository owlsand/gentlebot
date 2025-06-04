#!/usr/bin/env bash
# dev_run.sh — auto-restarting bot for development
# Requires: pip install watchdog

# Activate virtual environment
source venv/bin/activate
export env=TEST

# Start the bot and auto-restart on Python file changes
watchmedo auto-restart \
  --patterns="*.py;*.json" \
  --ignore-patterns="*__pycache__*" \
  --recursive \
  -- bash -c 'python main.py'