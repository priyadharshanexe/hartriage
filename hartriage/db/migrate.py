"""Apply database migrations: `python -m hartriage.db.migrate` (docker compose runs it)."""

from __future__ import annotations

import time
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from hartriage.core.config import get_settings

HERE = Path(__file__).parent


def alembic_config(url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(HERE / "migrations"))
    config.set_main_option(
        "sqlalchemy.url", (url or get_settings().database_url).replace("%", "%%")
    )
    return config


def wait_for_database(url: str, seconds: float = 30) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            with create_engine(url).connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception:
            if time.monotonic() > deadline:
                raise
            time.sleep(1)


def main() -> None:
    url = get_settings().database_url
    wait_for_database(url)
    command.upgrade(alembic_config(url), "head")
    print("migrations applied")


if __name__ == "__main__":
    main()
