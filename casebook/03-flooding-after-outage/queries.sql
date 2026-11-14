-- Case 03: a backlog after an outage, met by the receiver's rate limiter.

-- 1. Attempts per outcome. 'connect' = the outage; 429 = the rate limiter afterwards.
SELECT coalesce(a.status_code::text, a.error_kind) AS outcome, count(*) AS attempts
FROM attempts a
JOIN deliveries d ON d.id = a.delivery_id
WHERE d.endpoint_id = :endpoint_id
GROUP BY 1
ORDER BY 2 DESC;

-- 2. Did we honour Retry-After? For every 429, the receiver's Retry-After and how long
--    Relay actually waited before trying that delivery again.
SELECT (a.response_headers ->> 'retry-after')::int                       AS retry_after_s,
       round(extract(epoch FROM next.started_at - a.started_at))         AS waited_s,
       count(*)                                                          AS times
FROM attempts a
JOIN deliveries d ON d.id = a.delivery_id
JOIN LATERAL (
    SELECT n.started_at FROM attempts n
    WHERE n.delivery_id = a.delivery_id AND n.attempt_number = a.attempt_number + 1
) next ON true
WHERE d.endpoint_id = :endpoint_id AND a.status_code = 429
GROUP BY 1, 2
ORDER BY 2;

-- 3. The burst: deliveries attempted per second right after the outage ended.
SELECT date_trunc('second', a.started_at) AS second, count(*) AS requests,
       count(*) FILTER (WHERE a.status_code = 429) AS got_429
FROM attempts a
JOIN deliveries d ON d.id = a.delivery_id
WHERE d.endpoint_id = :endpoint_id AND a.error_kind IS DISTINCT FROM 'connect'
GROUP BY 1
ORDER BY 2 DESC
LIMIT 5;
