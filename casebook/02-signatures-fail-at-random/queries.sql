-- Case 02: which receiver node rejects our signatures? Relay stores each attempt's
-- response headers, so the receiver's own X-Served-By and Date headers are queryable.

-- 1. Outcome by receiver node.
SELECT a.response_headers ->> 'x-served-by'  AS node,
       count(*) FILTER (WHERE a.status_code = 200) AS ok,
       count(*) FILTER (WHERE a.status_code = 401) AS rejected
FROM attempts a
JOIN deliveries d ON d.id = a.delivery_id
WHERE d.endpoint_id = :endpoint_id
GROUP BY 1
ORDER BY 1;

-- 2. Each node's clock, from its Date header, against when we sent the attempt.
--    A node whose clock is minutes off cannot verify timestamps within a 5-minute tolerance.
SELECT a.response_headers ->> 'x-served-by'                                   AS node,
       a.started_at                                                          AS sent_at,
       (a.response_headers ->> 'date')::timestamptz                          AS node_clock,
       round(extract(epoch FROM (a.response_headers ->> 'date')::timestamptz - a.started_at)) AS skew_seconds,
       a.status_code,
       left(a.response_snippet, 80)                                          AS response
FROM attempts a
JOIN deliveries d ON d.id = a.delivery_id
WHERE d.endpoint_id = :endpoint_id
ORDER BY a.started_at
LIMIT 12;
