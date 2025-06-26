#!/usr/bin/env bash
# setup.sh - Create virtual environment and install dependencies
set -e
cd "$(dirname "$0")"

if [[ ! -d "venv" ]]; then
    python3 -m venv venv
fi

source venv/bin/activate

python -m pip install --upgrade pip

python -m pip install -r requirements.txt

# Optional extras used by certain cogs
python -m pip install python-dateutil pytz beautifulsoup4 yfinance matplotlib pandas timezonefinder huggingface-hub watchfiles watchdog

echo "Setup complete. Activate the environment with 'source venv/bin/activate'"
