-- Case 07: what are the API's database connections doing?

-- 1. Connections by state and what they wait for.
SELECT state, wait_event_type, wait_event, count(*)
FROM pg_stat_activity
WHERE datname = 'relay' AND backend_type = 'client backend' AND pid <> pg_backend_pid()
GROUP BY 1, 2, 3
ORDER BY 4 DESC;

-- 2. Who is blocking them, and for how long.
SELECT blocker.pid,
       now() - blocker.xact_start AS running_for,
       left(blocker.query, 70)   AS blocking_query,
       count(*)                  AS sessions_waiting
FROM pg_stat_activity waiting
JOIN LATERAL unnest(pg_blocking_pids(waiting.pid)) AS b(pid) ON true
JOIN pg_stat_activity blocker ON blocker.pid = b.pid
GROUP BY 1, 2, 3;
