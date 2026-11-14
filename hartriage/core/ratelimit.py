"""A fixed-window counter in Redis, for sign-in and sign-up attempts."""

from __future__ import annotations

from functools import lru_cache

import redis
import structlog

from hartriage.core.config import Settings
from hartriage.core.errors import TooManyRequests

log = structlog.get_logger()


@lru_cache
def _client(url: str) -> redis.Redis:
    return redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)


def limit(settings: Settings, key: str, max_calls: int, window_seconds: int) -> None:
    try:
        client = _client(settings.redis_url)
        name = f"hartriage:rl:{key}"
        count = int(client.incr(name))
        if count == 1:
            client.expire(name, window_seconds)
    except redis.RedisError:
        log.warning("rate_limit_unavailable")  # fail open: Redis down must not lock everyone out
        return
    if count > max_calls:
        raise TooManyRequests("Too many attempts. Wait a minute and try again.")
