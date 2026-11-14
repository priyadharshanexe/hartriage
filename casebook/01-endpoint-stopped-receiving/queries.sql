-- Case 01: deliveries to this customer's endpoint that fail before any HTTP response.
-- error_kind = 'tls' means the TLS handshake failed: no request ever reached their app.

-- 1. The endpoint's recent attempts, newest first.
SELECT e.url,
       a.attempt_number,
       a.started_at,
       a.duration_ms,
       a.status_code,
       a.error_kind,
       left(a.response_snippet, 90) AS error
FROM attempts a
JOIN deliveries d ON d.id = a.delivery_id
JOIN endpoints e ON e.id = d.endpoint_id
WHERE e.url = 'https://expired.badssl.com/'
ORDER BY a.started_at DESC
LIMIT 10;

-- 2. The delivery's own record carries the full error text.
SELECT d.status, d.attempts, d.next_attempt_at, d.last_error
FROM deliveries d
JOIN endpoints e ON e.id = d.endpoint_id
WHERE e.url = 'https://expired.badssl.com/'
ORDER BY d.created_at DESC
LIMIT 5;

-- 3. When did this endpoint last succeed, and what has failed since? (The "since when" an
--    agent needs for the reply. On the customer's real endpoint, the first TLS failure
--    lines up with the certificate's expiry date.)
SELECT e.url,
       max(a.started_at) FILTER (WHERE a.error_kind IS NULL AND a.status_code < 300) AS last_success,
       min(a.started_at) FILTER (WHERE a.error_kind = 'tls')                         AS first_tls_failure,
       count(*)          FILTER (WHERE a.error_kind = 'tls')                         AS tls_failures
FROM attempts a
JOIN deliveries d ON d.id = a.delivery_id
JOIN endpoints e ON e.id = d.endpoint_id
WHERE e.url = 'https://expired.badssl.com/'
GROUP BY e.url;

-- 4. Is it only this customer? TLS failures by endpoint over the last day.
SELECT e.url, count(*) AS tls_failures
FROM attempts a
JOIN deliveries d ON d.id = a.delivery_id
JOIN endpoints e ON e.id = d.endpoint_id
WHERE a.error_kind = 'tls' AND a.started_at > now() - interval '1 day'
GROUP BY e.url
ORDER BY tls_failures DESC;
