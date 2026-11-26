#!/bin/bash
# Render: migrate, then run the API and Caddy in one container.
# If either exits, the container exits and Render restarts it.
set -eu
python -m hartriage.db.migrate
uvicorn --factory hartriage.main:create_app --host 127.0.0.1 --port 8001 --no-access-log --proxy-headers --forwarded-allow-ips 127.0.0.1 &
caddy run --config /etc/caddy/Caddyfile --adapter caddyfile &
wait -n
exit 1
