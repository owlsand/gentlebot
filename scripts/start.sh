#!/usr/bin/env bash
set -e

# Wait for Postgres to accept connections
PGHOST=${PGHOST:-db}
PGPORT=${PGPORT:-5432}
PGUSER=${PG_USER:-${PGUSER:-postgres}}
PGDATABASE=${PG_DB:-${PGDATABASE:-postgres}}

until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" >/dev/null 2>&1; do
  echo "Waiting for Postgres at $PGHOST:$PGPORT..."
  sleep 2
done

# Apply migrations
alembic upgrade head

# Optionally prune dangling Docker images older than 24h
if [[ "${DOCKER_PRUNE:-0}" == "1" ]] && [[ -S /var/run/docker.sock ]]; then
  docker image prune -f --filter "until=24h" >/dev/null 2>&1 || true
fi

exec python -m gentlebot
