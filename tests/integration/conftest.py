"""Integration tests: the real API and tasks against real PostgreSQL and Redis.

    docker compose up -d postgres redis
    uv run pytest tests/integration tests/helpdesk

Each run builds a fresh `hartriage_test` database from the migrations. Object
storage is the in-memory backend (the S3 backend has its own test), Celery runs
tasks inline, and helpdesk calls go to tools/fake_helpdesk in-process.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ADMIN_URL = os.environ.get(
    "HARTRIAGE_TEST_ADMIN_DATABASE_URL",
    "postgresql+psycopg://hartriage:hartriage@localhost:5436/postgres",
)
TEST_DB = "hartriage_test"
TEST_URL = make_url(ADMIN_URL).set(database=TEST_DB).render_as_string(hide_password=False)

os.environ.update(
    {
        "HARTRIAGE_ENVIRONMENT": "test",
        "HARTRIAGE_DATABASE_URL": TEST_URL,
        "HARTRIAGE_REDIS_URL": os.environ.get(
            "HARTRIAGE_TEST_REDIS_URL", "redis://localhost:6380/1"
        ),
        "HARTRIAGE_STORAGE_BACKEND": "memory",
        "HARTRIAGE_CELERY_EAGER": "true",
        "HARTRIAGE_HELPDESK_BASE_URL_OVERRIDE": "http://testserver",
        "HARTRIAGE_LOGIN_ATTEMPTS_PER_MINUTE": "1000",
        "HARTRIAGE_API_PUBLIC_URL": "http://testserver",
    }
)


def _database_available() -> bool:
    try:
        with create_engine(ADMIN_URL).connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    if not _database_available():
        pytest.skip("PostgreSQL is not running (docker compose up -d postgres redis)")
    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    engine.dispose()
    from alembic import command

    from hartriage.db.migrate import alembic_config

    command.upgrade(alembic_config(TEST_URL), "head")
    yield


@pytest.fixture(autouse=True)
def _clean(database: None) -> Iterator[None]:
    from hartriage.core.config import get_settings
    from hartriage.db.session import engine
    from hartriage.storage.s3 import _memory
    from tools.fake_helpdesk import app as fake

    get_settings.cache_clear()
    import redis

    redis.Redis.from_url(get_settings().redis_url).flushdb()  # rate-limit counters
    _memory.objects.clear()
    fake.TICKETS.clear()
    fake.UPLOADS.clear()
    fake.FAIL_NEXT.clear()
    fake.CALLS.clear()
    fake.ZD_TOKENS.clear()
    yield
    with engine().begin() as conn:
        tables = (
            "audit_log, posted_notes, webhook_receipts, entries, findings, analyses, artifacts, "
            "cases, helpdesk_connections, invitations, refresh_tokens, memberships, users, organizations"
        )
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def client() -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from hartriage.helpdesk import registry
    from hartriage.main import create_app
    from hartriage.worker.celery_app import app as celery
    from tools.fake_helpdesk.app import app as fake_app

    celery.conf.task_always_eager = True
    celery.conf.task_eager_propagates = True
    # Each helpdesk client gets its own in-process transport, as each gets its own
    # connection pool in production. Starlette's test transport closes every open
    # response when it is closed, so one shared by threads breaks the others.
    registry.TEST_TRANSPORT = lambda: TestClient(fake_app)._transport
    with TestClient(create_app()) as c:
        yield c
    registry.TEST_TRANSPORT = None


class Api:
    """A signed-in user, for tests."""

    def __init__(self, client: Any, token: str, org_id: str) -> None:
        self.client, self.token, self.org_id = client, token, org_id

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def get(self, url: str, **kw: Any) -> Any:
        return self.client.get(url, headers=self.headers, **kw)

    def post(self, url: str, **kw: Any) -> Any:
        return self.client.post(url, headers={**self.headers, **kw.pop("headers", {})}, **kw)

    def patch(self, url: str, **kw: Any) -> Any:
        return self.client.patch(url, headers=self.headers, **kw)

    def put(self, url: str, **kw: Any) -> Any:
        return self.client.put(url, headers=self.headers, **kw)

    def delete(self, url: str, **kw: Any) -> Any:
        return self.client.delete(url, headers=self.headers, **kw)

    def upload(self, content: bytes, filename: str = "session.har") -> Any:
        return self.post(
            f"/v1/uploads?filename={filename}",
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )


def register(client: Any, email: str = "admin@example.com", org: str = "Acme Support") -> Api:
    response = client.post(
        "/v1/auth/register",
        json={
            "email": email,
            "password": "correct horse battery",
            "organization": org,
            "name": "Ada",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    return Api(client, body["access_token"], body["org_id"])


@pytest.fixture
def admin(client: Any) -> Api:
    return register(client)


def member(client: Any, admin: Api, email: str, role: str) -> Api:
    invite = admin.post("/v1/invitations", json={"email": email, "role": role}).json()
    token = invite["invite_url"].split("#", 1)[1]
    response = client.post(
        "/v1/auth/accept-invite", json={"token": token, "password": "another long password"}
    )
    assert response.status_code == 200, response.text
    return Api(client, response.json()["access_token"], response.json()["org_id"])
