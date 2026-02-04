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

echo "Setup complete. Activate the environment with 'source venv/bin/activate'"
echo "Run tests with: make test"
