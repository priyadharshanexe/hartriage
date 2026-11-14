-- Case 08: one delivery, sent twice. The first send was cut off by the worker crash,
-- so it never got an attempt row; the second send is the only one recorded.

-- 1. The delivery and its event: the webhook-id the receiver saw both times is the
--    delivery's event id, which never changes between sends.
SELECT d.id AS delivery_id, d.event_id AS webhook_id, d.status, d.attempts, d.created_at, d.updated_at
FROM deliveries d
WHERE d.id = :delivery_id;

-- 2. Recorded attempts. Note the gap between the event and the first recorded attempt:
--    the lease (60 s) had to run out before the delivery could be sent again.
SELECT a.attempt_number, a.started_at, a.duration_ms, a.status_code,
       a.request_headers ->> 'webhook-id' AS webhook_id_sent,
       round(extract(epoch FROM a.started_at - d.created_at)) AS seconds_after_event
FROM attempts a
JOIN deliveries d ON d.id = a.delivery_id
WHERE d.id = :delivery_id
ORDER BY a.started_at;
