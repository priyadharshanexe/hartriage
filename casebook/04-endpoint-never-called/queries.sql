-- Case 04: deliveries Relay refused to make because the destination is not public.

-- 1. Blocked attempts, with the reason Relay recorded.
SELECT e.url, d.status, d.attempts, d.last_error
FROM deliveries d
JOIN endpoints e ON e.id = d.endpoint_id
WHERE d.last_error LIKE 'ssrf_blocked%'
ORDER BY d.created_at DESC
LIMIT 5;

-- 2. Endpoints that have never had a single successful attempt but do have blocked ones:
--    a list support can work through before customers notice.
SELECT e.id, e.url, e.created_at,
       count(a.*) FILTER (WHERE a.error_kind = 'ssrf_blocked') AS blocked_attempts
FROM endpoints e
JOIN deliveries d ON d.endpoint_id = e.id
JOIN attempts a ON a.delivery_id = d.id
GROUP BY e.id
HAVING count(a.*) FILTER (WHERE a.status_code BETWEEN 200 AND 299) = 0
   AND count(a.*) FILTER (WHERE a.error_kind = 'ssrf_blocked') > 0
ORDER BY e.created_at DESC;
