#!/usr/bin/env bash
source venv/bin/activate
export env=PROD
# Console output defaults to INFO; override via LOG_LEVEL if needed
export LOG_LEVEL=${LOG_LEVEL:-INFO}
python -m gentlebot
