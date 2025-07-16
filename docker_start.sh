#!/usr/bin/env bash
set -e

# docker_start.sh - wait for Postgres, run migrations, prune images, start bot

PGHOST=${PGHOST:-db}
PGPORT=${PGPORT:-5432}
PGUSER=${PG_USER:-${PGUSER:-postgres}}
PGDATABASE=${PG_DB:-${PGDATABASE:-postgres}}

# Wait for Postgres to accept connections
until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" >/dev/null 2>&1; do
  echo "Waiting for Postgres at $PGHOST:$PGPORT..."
  sleep 2
done

# Run database migrations
alembic upgrade head

# Prune dangling Docker images to save disk space
if command -v docker >/dev/null 2>&1; then
  docker image prune -f >/dev/null 2>&1 || true
fi

# Launch the bot
exec python -m gentlebot
