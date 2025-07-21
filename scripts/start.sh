#!/usr/bin/env bash
set -e

# Skip Postgres checks when running in CI
if [[ "${SKIP_DB:-0}" != "1" ]]; then
  # Wait for Postgres to accept connections
  PG_HOST=${PGHOST:-db}
  PG_PORT=${PGPORT:-5432}
  PG_USER=${PGUSER:-postgres}
  PG_DB=${PGDB:-postgres}

  until pg_isready -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" >/dev/null 2>&1; do
    echo "Waiting for Postgres at $PG_HOST:$PG_PORT..."
    sleep 2
  done

  # Apply migrations
  alembic upgrade head

  # Run backfill scripts after migrations
  BACKFILL_DAYS=${BACKFILL_DAYS:-90}
  python gentlebot/backfill_commands.py --days "$BACKFILL_DAYS" || true
  python gentlebot/backfill_archive.py --days "$BACKFILL_DAYS" || true
else
  echo "SKIP_DB=1 - skipping Postgres availability checks"
fi

# Optionally prune dangling Docker images older than 24h
if [[ "${DOCKER_PRUNE:-0}" == "1" ]] && [[ -S /var/run/docker.sock ]]; then
  count=$(docker image prune -af --filter "until=24h" -q | wc -l)
  echo "Pruned $count old layers"
fi

exec python -m gentlebot "$@"
