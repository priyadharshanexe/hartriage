#!/usr/bin/env bash
# Case 01: "My endpoint stopped receiving webhooks" — the receiver's TLS certificate expired.
# Needs the casebook Relay (../relay/up.sh) and internet access (expired.badssl.com).
cd "$(dirname "$0")"
. ../relay/lib.sh

say "Set up an organisation and an endpoint whose certificate has expired"
relay_setup case01
endpoint="$(relay_post /v1/endpoints '{"url":"https://expired.badssl.com/","description":"customer receiver (cert expired)"}')"
echo "$endpoint" | json '["url"]'

say "Send an order.paid event"
event_id="$(send_event order.paid '{"order_id": 1042, "amount": 1999}' | json '["id"]')"
delivery_id="$(delivery_for "$event_id")"
wait_for_attempts "$delivery_id" 2
show_attempts "$delivery_id"

say "What the database says (queries.sql)"
relay_sql < queries.sql

say "Verification: the customer renews the certificate (simulated by pointing the endpoint at a host with a valid one), then the stuck delivery is replayed"
endpoint_id="$(echo "$endpoint" | json '["id"]')"
relay_patch "/v1/endpoints/$endpoint_id" '{"url":"https://httpbin.org/post"}' | json '["url"]'
relay_post "/v1/deliveries/$delivery_id/replay" '{}' >/dev/null
before="$(relay_get "/v1/deliveries/$delivery_id" | json '["attempts"]')"
wait_for_attempts "$delivery_id" "$((before + 1))"
show_attempts "$delivery_id"
