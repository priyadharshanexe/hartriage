#!/usr/bin/env bash
# Shared helpers for the casebook reproductions. Source it: . ../relay/lib.sh
# Needs: curl, docker, and Python 3 (for reading JSON; jq is not assumed).
set -euo pipefail

RELAY_URL="${RELAY_URL:-http://localhost:8101}"
RELAY_DB_CONTAINER="${RELAY_DB_CONTAINER:-relay-casebook-postgres-1}"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT

for candidate in python3 python; do
  if "$candidate" -c 'import sys' >/dev/null 2>&1; then PY="$candidate"; break; fi
done

# json '["id"]' < response.json  → prints that field
json() { "$PY" -c "import json,sys; v=json.load(sys.stdin)$1; print(v if isinstance(v,str) else json.dumps(v))"; }

say() { if [ -t 1 ]; then printf '\n\033[1m== %s\033[0m\n' "$*"; else printf '\n== %s\n' "$*"; fi; }

# Dashboard calls (cookie session)
relay_post() { curl -sS -b "$JAR" -c "$JAR" -H 'Content-Type: application/json' -X POST "$RELAY_URL$1" -d "$2"; }
relay_get() { curl -sS -b "$JAR" -c "$JAR" "$RELAY_URL$1"; }
relay_patch() { curl -sS -b "$JAR" -c "$JAR" -H 'Content-Type: application/json' -X PATCH "$RELAY_URL$1" -d "$2"; }

# One organisation per case, signed in, with a new API key in $API_KEY. The account is
# reused on re-runs: Relay limits sign-ups to 10 an hour per address.
relay_setup() {
  local email="casebook-$1@example.com" password="casebook password 1"
  if ! curl -sSf -b "$JAR" -c "$JAR" -H 'Content-Type: application/json' -X POST "$RELAY_URL/v1/auth/login"       -d "{\"email\":\"$email\",\"password\":\"$password\"}" >/dev/null 2>&1; then
    relay_post /v1/auth/register "{\"email\":\"$email\",\"password\":\"$password\",\"organization_name\":\"Casebook $1\"}" >/dev/null
  fi
  API_KEY="$(relay_post /v1/api-keys '{"name":"casebook"}' | json '["key"]')"
  export API_KEY
}

# send_event TYPE PAYLOAD_JSON  → prints the API response
send_event() {
  curl -sS -H "Authorization: Bearer $API_KEY" -H 'Content-Type: application/json' \
    -X POST "$RELAY_URL/v1/events" -d "{\"type\":\"$1\",\"payload\":$2}"
}

# psql against the casebook's Relay database
relay_sql() { docker exec -i "$RELAY_DB_CONTAINER" psql -U relay -d relay -v ON_ERROR_STOP=1 "$@"; }

# delivery_for EVENT_ID  → the id of the event's (first) delivery
delivery_for() {
  for _ in $(seq 1 30); do
    id="$(relay_get "/v1/deliveries?limit=50" | "$PY" -c "import json,sys; print(next((d['id'] for d in json.load(sys.stdin)['items'] if d['event_id']=='$1'), ''))")"
    [ -n "$id" ] && { echo "$id"; return 0; }
    sleep 1
  done
  return 1
}

# wait_for_attempts DELIVERY_ID N  → waits until the delivery has made N attempts
wait_for_attempts() {
  for _ in $(seq 1 180); do
    n="$(relay_get "/v1/deliveries/$1" | json '["attempts"]' 2>/dev/null || echo 0)"
    [ "${n:-0}" -ge "$2" ] && return 0
    sleep 1
  done
  echo "timed out waiting for $2 attempts" >&2
  return 1
}

# show_attempts DELIVERY_ID  → one line per attempt, as an agent reads them
show_attempts() {
  relay_get "/v1/deliveries/$1" | "$PY" -c "
import json, sys
d = json.load(sys.stdin)
print(f\"delivery {d['id']}  status={d['status']}  attempts={d['attempts']}  endpoint={d['endpoint_url']}\")
print(f\"  last_error: {d['last_error']}\")
for a in d['attempt_log']:
    print(f\"  #{a['attempt_number']} {a['started_at'][11:19]}  {a['duration_ms']:>5} ms  status={a['status_code']}  error={a['error_kind']}  {' '.join((a['response_snippet'] or '').split())[:100]}\")
"
}
