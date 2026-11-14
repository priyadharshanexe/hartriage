#!/usr/bin/env bash
# Case 06: "Signatures broke after we rotated the secret" — the receiver kept the old
# secret, and the overlap window ended. Needs ../relay/up.sh (overlap set to 1 hour).
cd "$(dirname "$0")"
. ../relay/lib.sh
PORT="${PORT:-9916}"

start_receiver() {  # start_receiver SECRET
  [ -n "${receiver:-}" ] && { kill "$receiver" 2>/dev/null || true; wait "$receiver" 2>/dev/null || true; }
  SECRET="$1" "$PY" receiver.py "$PORT" >> receiver.log 2>&1 &
  receiver=$!
  sleep 1
}
deliver() {  # deliver LABEL → sends one event, waits for its first attempt, prints it
  local id d
  id="$(send_event subscription.renewed "{\"label\": \"$1\"}" | json '["id"]')"
  d="$(delivery_for "$id" "$endpoint_id")"
  wait_for_attempts "$d" 1
  show_attempts "$d" | sed -n '3p'
  echo "$d" >> deliveries.txt
}
: > receiver.log; : > deliveries.txt
trap 'kill ${receiver:-0} 2>/dev/null; rm -f "$JAR" deliveries.txt' EXIT

say "Endpoint created; the receiver is deployed with secret A"
relay_setup case06
endpoint="$(relay_post /v1/endpoints "{\"url\":\"http://host.docker.internal:$PORT/hook\"}")"
endpoint_id="$(echo "$endpoint" | json '["id"]')"
secret_a="$(echo "$endpoint" | json '["secret"]')"
start_receiver "$secret_a"
deliver "before rotation"

say "The customer rotates the secret in the dashboard (secret B). Old one valid for the overlap"
rotated="$(relay_post "/v1/endpoints/$endpoint_id/rotate-secret" '{}')"
secret_b="$(echo "$rotated" | json '["secret"]')"
echo "old secret valid until $(echo "$rotated" | json '["previous_secret_expires_at"]')"
deliver "during overlap"

say "The overlap ends (fast-forwarded here by expiring the old secret in the database)"
relay_sql -c "UPDATE endpoint_secrets SET expires_at = now() - interval '1 second' WHERE endpoint_id = '$endpoint_id' AND expires_at IS NOT NULL;" >/dev/null
deliver "after overlap"

say "Receiver log"
cat receiver.log

say "SQL (queries.sql)"
relay_sql -v endpoint_id="'$endpoint_id'" < queries.sql

say "Fix: the customer deploys secret B; the refused delivery succeeds on its next retry"
start_receiver "$secret_b"
refused="$(tail -1 deliveries.txt)"
wait_for_attempts "$refused" 2
show_attempts "$refused"
