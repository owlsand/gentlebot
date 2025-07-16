#!/usr/bin/env bash
set -e

# Wait for Postgres to accept connections
PGHOST=${PGHOST:-db}
PGPORT=${PGPORT:-5432}
PGUSER=${PGUSER:-postgres}
PGDATABASE=${PGDATABASE:-postgres}

until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" >/dev/null 2>&1; do
  echo "Waiting for Postgres at $PGHOST:$PGPORT..."
  sleep 2
done

# Apply migrations
alembic upgrade head

# Optionally prune dangling Docker images older than 24h
if [[ "${DOCKER_PRUNE:-0}" == "1" ]] && [[ -S /var/run/docker.sock ]]; then
  count=$(docker image prune -af --filter "until=24h" -q | wc -l)
  echo "Pruned $count old layers"
fi

exec python -m gentlebot "$@"
