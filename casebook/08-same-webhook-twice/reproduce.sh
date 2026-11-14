#!/usr/bin/env bash
# Case 08: "We received the same webhook twice" — Relay's worker died mid-delivery and
# the delivery was re-sent after its lease expired. Needs ../relay/up.sh. ~3 minutes.
cd "$(dirname "$0")"
. ../relay/lib.sh
PORT="${PORT:-9918}"
WORKER="${WORKER:-relay-casebook-worker-1}"

start_receiver() {  # start_receiver DEDUPE
  [ -n "${receiver:-}" ] && { kill "$receiver" 2>/dev/null || true; wait "$receiver" 2>/dev/null || true; }
  DELAY=8 DEDUPE="$1" "$PY" receiver.py "$PORT" >> receiver.log 2>&1 &
  receiver=$!
  sleep 1
}
crash_during_delivery() {  # crash_during_delivery ORDER_ID → prints the delivery id
  local before id d
  before="$(wc -l < receiver.log)"
  id="$(send_event order.paid "{\"order_id\": $1}" | json '["id"]')"
  until [ "$(wc -l < receiver.log)" -gt "$before" ]; do sleep 0.2; done
  docker kill "$WORKER" >/dev/null && echo "worker killed while the receiver was still working" >&2
  sleep 2
  docker start "$WORKER" >/dev/null && echo "worker restarted" >&2
  d="$(delivery_for "$id" "$endpoint_id")"
  for _ in $(seq 1 150); do
    [ "$(relay_get "/v1/deliveries/$d" | json '["status"]')" = "succeeded" ] && break
    sleep 1
  done
  echo "$d"
}
: > receiver.log
trap 'kill ${receiver:-0} 2>/dev/null; rm -f "$JAR"' EXIT

say "Setup: an endpoint whose receiver ships the order, then answers after 8 s"
relay_setup case08
endpoint="$(relay_post /v1/endpoints "{\"url\":\"http://host.docker.internal:$PORT/hook\"}")"
endpoint_id="$(echo "$endpoint" | json '["id"]')"
start_receiver 0

say "An order.paid event; Relay's worker is killed while the receiver is still working"
d1="$(crash_during_delivery 7001)"
show_attempts "$d1"

say "Receiver log"
cat receiver.log

say "Relay's worker log: the expired lease was recovered"
docker logs --since 5m "$WORKER" 2>&1 | grep -E "recovered_expired_leases" | tail -1 | "$PY" -c "import json,sys; [print({k: json.loads(l).get(k) for k in ('timestamp','event','count')}) for l in sys.stdin]"

say "SQL (queries.sql)"
relay_sql -v delivery_id="'$d1'" < queries.sql

say "Fix: the receiver deduplicates on webhook-id; the same crash again"
: > receiver.log
start_receiver 1
d2="$(crash_during_delivery 7002)"
show_attempts "$d2"
cat receiver.log
