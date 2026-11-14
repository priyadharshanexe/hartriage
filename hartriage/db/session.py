"""One synchronous SQLAlchemy engine, shared by the API (thread pool) and the Celery workers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from hartriage.core.config import get_settings


@lru_cache
def engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_size=settings.database_pool_size,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache
def session_factory() -> sessionmaker[Session]:
    return sessionmaker(engine(), expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """A session that commits on success and rolls back on error (for workers)."""
    session = session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    session = session_factory()()
    try:
        yield session
    finally:
        session.close()
