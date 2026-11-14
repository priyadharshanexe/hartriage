#!/usr/bin/env bash
# Case 04: "Our endpoint never gets called" — the endpoint's hostname resolves to an
# address Relay refuses to connect to (SSRF protection). Needs ../relay/up.sh.
#
# Production Relay blocks every private range. The local stack allows private ranges so
# receivers on your machine work, so this reproduction uses a hostname that resolves to
# a link-local address (169.254.0.0/16), which stays blocked everywhere. The code path is
# the same: resolve the name, check every address, refuse before connecting.
cd "$(dirname "$0")"
. ../relay/lib.sh
HOST="${HOST:-169.254.169.254.nip.io}"

say "The customer registers their endpoint by name"
relay_setup case04
endpoint="$(relay_post /v1/endpoints "{\"url\":\"http://$HOST/webhooks/relay\",\"description\":\"customer receiver\"}")"
echo "$endpoint" | json '["url"]'

say "Registering the address itself is refused at once, with the reason"
relay_post /v1/endpoints '{"url":"http://169.254.169.254/webhooks/relay"}' | json ''

say "An event is sent"
event_id="$(send_event customer.updated '{"customer_id": 77}' | json '["id"]')"
delivery_id="$(delivery_for "$event_id")"
wait_for_attempts "$delivery_id" 2
show_attempts "$delivery_id"

say "What the name resolves to, asked from inside Relay's worker container"
docker exec relay-casebook-worker-1 python -c "import socket; print('$HOST ->', sorted({i[4][0] for i in socket.getaddrinfo('$HOST', 80)}))"

say "SQL (queries.sql)"
relay_sql < queries.sql

say "Verification: the customer moves the endpoint to a public HTTPS address; the waiting delivery goes through"
endpoint_id="$(echo "$endpoint" | json '["id"]')"
relay_patch "/v1/endpoints/$endpoint_id" '{"url":"https://httpbin.org/post"}' | json '["url"]'
before="$(relay_get "/v1/deliveries/$delivery_id" | json '["attempts"]')"
wait_for_attempts "$delivery_id" "$((before + 1))"
show_attempts "$delivery_id"
