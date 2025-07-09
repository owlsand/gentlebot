#!/usr/bin/env bash
source venv/bin/activate
export env=PROD
export LOG_LEVEL=DEBUG
python main.py
