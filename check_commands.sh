#!/usr/bin/env bash
# check_commands.sh
# Usage: ./check_commands.sh
# Reads APP_ID, GUILD_ID, and TOKEN from .env (if present) or environment.

set -euo pipefail

# Load environment variables from .env if it exists
if [[ -f ".env" ]]; then
  set -o allexport
  source ".env"
  set +o allexport
fi

# Map .env keys to script variables
# .env should define DISCORD_APPLICATION_ID, DISCORD_GUILD_ID, and DISCORD_TOKEN
APP_ID="${DISCORD_APPLICATION_ID:-}"
GUILD_ID="${DISCORD_GUILD_ID:-}"
TOKEN="${DISCORD_TOKEN:-}"

if [[ -z "${APP_ID}" || -z "${GUILD_ID}" || -z "${TOKEN}" ]]; then
  echo "Error: DISCORD_APPLICATION_ID, DISCORD_GUILD_ID, and DISCORD_TOKEN must be set in .env or environment."
  echo "Example .env content:"
  echo "  DISCORD_APPLICATION_ID=<application id>"
  echo "  DISCORD_GUILD_ID=<guild id>"
  echo "  DISCORD_TOKEN=<bot token>"
  exit 1
fi

# Debug: show loaded variables
echo "Using DISCORD_APPLICATION_ID=$APP_ID"
echo "Using DISCORD_GUILD_ID=$GUILD_ID"

echo "Fetching slash commands for /stock..."
# Fetch guild commands and filter for 'stock'

echo "--- Guild Commands (/stock) ---"
# fetch and filter
guild_output=$(curl -s -X GET \
  -H "Authorization: Bot $TOKEN" \
  -H "Content-Type: application/json" \
  "https://discord.com/api/v10/applications/$APP_ID/guilds/$GUILD_ID/commands" \
  | tee /tmp/all_commands.json \
  | jq '.[] | select(.name=="stock") | .options')
if [[ -n "$guild_output" ]]; then
  echo "$guild_output"
else
  echo "No guild-scoped /stock command found. Falling back to global commands..."
  echo "--- Global Commands (/stock) ---"
  curl -s -X GET \
    -H "Authorization: Bot $TOKEN" \
    -H "Content-Type: application/json" \
    "https://discord.com/api/v10/applications/$APP_ID/commands" \
    | jq '.[] | select(.name=="stock") | .options'
fi
