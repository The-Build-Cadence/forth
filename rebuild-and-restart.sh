#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
if [[ ! -f "$COMPOSE_FILE" ]]; then
    echo "Compose file not found: $COMPOSE_FILE" >&2
    exit 1
fi

compose_args=(-f "$COMPOSE_FILE")
if [[ "$COMPOSE_FILE" == "docker-compose.yml" && -f "docker-compose.override.yml" ]]; then
    compose_args+=(-f docker-compose.override.yml)
fi
echo "Using compose file: $COMPOSE_FILE"
echo "Rebuilding services..."
docker compose "${compose_args[@]}" build

echo "Recreating and restarting services..."
docker compose "${compose_args[@]}" up -d --force-recreate

echo "Done."
exit 0
