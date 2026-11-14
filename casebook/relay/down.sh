#!/usr/bin/env bash
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
RELAY_DIR="${RELAY_DIR:-$here/../../../webhook}"
docker compose -p relay-casebook -f "$RELAY_DIR/docker-compose.yml" -f "$here/compose.override.yml" down -v
