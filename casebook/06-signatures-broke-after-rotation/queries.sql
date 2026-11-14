-- Case 06: signatures failing after a secret rotation.

-- 1. The endpoint's secrets: when each became active and when it stopped being used.
--    (The ciphertext is never selected.)
SELECT id, active_from, expires_at,
       CASE WHEN expires_at IS NULL OR expires_at > now() THEN 'signing' ELSE 'expired' END AS state
FROM endpoint_secrets
WHERE endpoint_id = :endpoint_id
ORDER BY active_from;

-- 2. Who rotated it, and when (the audit log).
SELECT al.at, u.email AS actor, al.action
FROM audit_log al
LEFT JOIN users u ON u.id = al.actor_user_id
WHERE al.target_id = :endpoint_id::text AND al.action = 'endpoint.secret_rotated'
ORDER BY al.at;

-- 3. Each attempt, how many signatures we sent, and what the receiver said.
SELECT a.started_at,
       a.status_code,
       array_length(string_to_array(a.request_headers ->> 'webhook-signature', ' '), 1) AS signatures_sent,
       left(a.response_snippet, 70) AS receiver_said
FROM attempts a
JOIN deliveries d ON d.id = a.delivery_id
WHERE d.endpoint_id = :endpoint_id
ORDER BY a.started_at;
