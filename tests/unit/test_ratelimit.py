"""The rate limiter tells people how long to wait, from the window it actually uses."""

from __future__ import annotations

import pytest

from hartriage.core import ratelimit
from hartriage.core.config import Settings
from hartriage.core.errors import TooManyRequests


class _FakeRedis:
    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def incr(self, name: str) -> int:
        self.counts[name] = self.counts.get(name, 0) + 1
        return self.counts[name]

    def expire(self, name: str, seconds: int) -> None:
        self.ttls[name] = seconds

    def ttl(self, name: str) -> int:
        return self.ttls.get(name, -1)


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> _FakeRedis:
    client = _FakeRedis()
    monkeypatch.setattr(ratelimit, "_client", lambda url: client)
    return client


def _exhaust(key: str, max_calls: int, window: int) -> str:
    settings = Settings()
    for _ in range(max_calls):
        ratelimit.limit(settings, key, max_calls, window)
    with pytest.raises(TooManyRequests) as caught:
        ratelimit.limit(settings, key, max_calls, window)
    return str(caught.value)


def test_hourly_window_says_how_many_minutes(fake: _FakeRedis) -> None:
    # Sign-up is 10 an hour: the message must not promise "a minute".
    message = _exhaust("register:1.2.3.4", 10, 3600)
    assert "60 minutes" in message
    assert "a minute" not in message


def test_remaining_time_is_rounded_up(fake: _FakeRedis) -> None:
    settings = Settings()
    for _ in range(3):
        ratelimit.limit(settings, "login:a@b.test", 3, 60)
    fake.ttls["hartriage:rl:login:a@b.test"] = 61  # just over a minute left
    with pytest.raises(TooManyRequests) as caught:
        ratelimit.limit(settings, "login:a@b.test", 3, 60)
    assert "2 minutes" in str(caught.value)


def test_one_minute_is_singular(fake: _FakeRedis) -> None:
    assert "Try again in 1 minute." in _exhaust("login:c@d.test", 5, 60)
