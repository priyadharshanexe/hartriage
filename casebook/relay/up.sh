#!/usr/bin/env bash
# Start the casebook's own copy of Relay. RELAY_DIR points at a checkout of
# https://github.com/priyadharshanexe/relay (default: ../../../webhook).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
RELAY_DIR="${RELAY_DIR:-$here/../../../webhook}"
docker compose -p relay-casebook -f "$RELAY_DIR/docker-compose.yml" -f "$here/compose.override.yml" up -d --build --wait "$@"
echo "Relay for the casebook: API http://localhost:8101, dashboard http://localhost:8181"
