from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from hartriage.db.models import Base
from tests.integration.conftest import TEST_URL

pytestmark = pytest.mark.integration


def test_models_and_migrations_agree() -> None:
    engine = create_engine(TEST_URL)
    with engine.connect() as conn:
        diff = compare_metadata(
            MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata
        )
    engine.dispose()
    assert diff == [], f"run: uv run alembic revision --autogenerate (differences: {diff})"
