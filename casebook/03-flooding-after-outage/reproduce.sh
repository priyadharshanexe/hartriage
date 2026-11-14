#!/usr/bin/env bash
# Case 03: "You're flooding us after an outage" — a backlog of retries meets the
# customer's rate limiter. Needs ../relay/up.sh. Takes about three minutes.
cd "$(dirname "$0")"
. ../relay/lib.sh
PORT="${PORT:-9913}"
N="${N:-30}"

say "The customer's endpoint is down (nothing listens on :$PORT); $N events arrive meanwhile"
relay_setup case03
endpoint="$(relay_post /v1/endpoints "{\"url\":\"http://host.docker.internal:$PORT/hook\",\"description\":\"customer receiver\"}")"
endpoint_id="$(echo "$endpoint" | json '["id"]')"
for i in $(seq 1 "$N"); do send_event order.paid "{\"order_id\": $i}" >/dev/null; done
sleep 3
relay_sql -c "SELECT d.status, count(*), min(a.error_kind) AS error FROM deliveries d JOIN attempts a ON a.delivery_id = d.id WHERE d.endpoint_id = '$endpoint_id' GROUP BY 1;"

say "The outage ends: the receiver is back, limited to 2 requests/s with Retry-After: 30"
RATE=2 RETRY_AFTER=30 "$PY" receiver.py "$PORT" > receiver.log 2>&1 &
receiver=$!
started=$SECONDS
trap 'kill $receiver 2>/dev/null; rm -f "$JAR"' EXIT
# Wait until every delivery has succeeded (they retry in waves on the schedule).
for _ in $(seq 1 600); do
  left="$(relay_sql -tA -c "SELECT count(*) FROM deliveries WHERE endpoint_id = '$endpoint_id' AND status <> 'succeeded';")"
  [ "$left" = "0" ] && break
  sleep 1
done
echo "backlog of $N delivered $((SECONDS - started)) s after the outage ended ($left still waiting)"

say "Receiver log: requests per second and status"
awk '{print $1, $2}' receiver.log | sort | uniq -c

say "SQL (queries.sql)"
relay_sql -v endpoint_id="'$endpoint_id'" < queries.sql

say "Fix: pace deliveries to the receiver's capacity (rate_limit_per_sec = 2), then send another $N"
relay_patch "/v1/endpoints/$endpoint_id" '{"rate_limit_per_sec": 2}' | json '["rate_limit_per_sec"]'
: > receiver.log
started=$SECONDS
for i in $(seq 1 "$N"); do send_event order.paid "{\"order_id\": $((1000 + i))}" >/dev/null; done
for _ in $(seq 1 120); do
  left="$(relay_sql -tA -c "SELECT count(*) FROM deliveries WHERE endpoint_id = '$endpoint_id' AND status <> 'succeeded';")"
  [ "$left" = "0" ] && break
  sleep 1
done
echo "$N new deliveries done in $((SECONDS - started)) s"
say "Receiver log after the fix"
awk '{print $2}' receiver.log | sort | uniq -c
