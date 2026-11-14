#!/usr/bin/env bash
# Case 07: "Event API is timing out" — a maintenance script holds a lock on the events
# table; ingestion requests wait on it while holding database connections, and the
# pool runs dry. Needs ../relay/up.sh. ~2 minutes.
cd "$(dirname "$0")"
. ../relay/lib.sh
relay_setup case07

say "Baseline: 20 concurrent events"
API_KEY="$API_KEY" "$PY" load.py "$RELAY_URL" 20 | tail -1

say "Incident: a backfill script takes a SHARE lock on events and runs for 70 s"
relay_sql -c "SELECT 1" >/dev/null
docker exec -i "$RELAY_DB_CONTAINER" psql -U relay -d relay -q -c \
  "BEGIN; LOCK TABLE events IN SHARE MODE; SELECT pg_sleep(70); COMMIT;" >/dev/null 2>&1 &
backfill=$!
sleep 2
API_KEY="$API_KEY" "$PY" load.py "$RELAY_URL" 40 > client.txt &
load=$!
sleep 12

say "Database during the incident (queries.sql)"
relay_sql < queries.sql

say "Health check during the incident"
curl -s -m 10 -o /dev/null -w "GET /readyz -> HTTP %{http_code} in %{time_total}s\n" "$RELAY_URL/readyz" || echo "GET /readyz -> no answer in 10 s"

wait $load
say "What the customer's integration saw"
cat client.txt
wait $backfill

say "Relay's API log for one of the 500s (looked up by the request id the customer sent)"
rid="$(grep ' 500 ' client.txt | head -1 | awk '{print $NF}')"
docker logs --since 3m relay-casebook-api-1 2>&1 | grep "$rid" | grep unhandled_error | "$PY" -c "
import json, sys
for line in sys.stdin:
    d = json.loads(line)
    last = [l for l in d.get('exception', '').splitlines() if l.strip()][-1]
    print(d['timestamp'], d['event'], d['request_id']); print('  ', last[:200])"

say "Metrics: POST /v1/events latency buckets"
curl -s "$RELAY_URL/metrics" | grep 'relay_http_request_duration_seconds_bucket{le=.*method="POST",route="/v1/events"\|route="/v1/events".*le="\(0.1\|1.0\|5.0\|10.0\|+Inf\)"'

say "After the backfill ended: 20 concurrent events again"
API_KEY="$API_KEY" "$PY" load.py "$RELAY_URL" 20 | tail -1
