#!/usr/bin/env bash
# Case 02: "Signature verification fails at random" — one receiver node's clock is
# 7 minutes slow, beyond the 5-minute tolerance. Needs ../relay/up.sh.
cd "$(dirname "$0")"
. ../relay/lib.sh
PORT="${PORT:-9912}"

say "Set up an endpoint on the customer's receiver (two nodes behind a load balancer)"
relay_setup case02
endpoint="$(relay_post /v1/endpoints "{\"url\":\"http://host.docker.internal:$PORT/hook\",\"description\":\"customer receiver\"}")"
endpoint_id="$(echo "$endpoint" | json '["id"]')"
SECRET="$(echo "$endpoint" | json '["secret"]')" CLOCK_SKEW_SECONDS=-420 "$PY" receiver.py "$PORT" > receiver.log 2>&1 &
receiver=$!
trap 'kill $receiver 2>/dev/null; rm -f "$JAR"' EXIT
sleep 1

say "Send six events"
ids=()
for i in 1 2 3 4 5 6; do ids+=("$(send_event invoice.created "{\"invoice\": $i}" | json '["id"]')"); done
deliveries=()
for id in "${ids[@]}"; do deliveries+=("$(delivery_for "$id")"); done
for d in "${deliveries[@]}"; do wait_for_attempts "$d" 1; done
sleep 2
for d in "${deliveries[@]}"; do show_attempts "$d"; done

say "Receiver log (what the customer sees)"
cat receiver.log

say "SQL (queries.sql)"
relay_sql -v endpoint_id="'$endpoint_id'" < queries.sql

say "Verification: web-2's clock is fixed (NTP restarted); the waiting deliveries retry on their own"
kill $receiver; wait $receiver 2>/dev/null || true
SECRET="$(echo "$endpoint" | json '["secret"]')" CLOCK_SKEW_SECONDS=0 "$PY" receiver.py "$PORT" >> receiver.log 2>&1 &
receiver=$!
for _ in $(seq 1 90); do
  pending=0
  for d in "${deliveries[@]}"; do
    [ "$(relay_get "/v1/deliveries/$d" | json '["status"]')" = "succeeded" ] || pending=$((pending + 1))
  done
  [ "$pending" -eq 0 ] && break
  sleep 1
done
for d in "${deliveries[@]}"; do show_attempts "$d"; done
