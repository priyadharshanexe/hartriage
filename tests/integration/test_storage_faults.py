"""Fault injection: storage and the database failing part-way through an upload.

The redacted file and its index are written before their rows exist. Whatever fails
after the first write (storage, the flush, the commit, the process), no object may
stay in storage without a row that owns it.
"""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from hartriage.core.config import get_settings
from hartriage.db.models import Artifact
from hartriage.db.session import session_scope
from hartriage.services.intake import index_key, intake
from hartriage.services.reconcile import reconcile
from hartriage.storage.s3 import MemoryStorage, _memory

pytestmark = pytest.mark.integration
HAR = (
    Path(__file__).resolve().parents[1] / "golden" / "hars" / "chromium" / "checkout-story.har"
).read_bytes()


def org_of(admin: Any) -> uuid.UUID:
    return uuid.UUID(admin.get("/v1/auth/me").json()["org_id"])


def objects() -> list[str]:
    return sorted(k for k in _memory.objects if k.startswith("orgs/"))


def run_intake(db: Any, org: uuid.UUID, storage: Any = None) -> Any:
    return intake(
        db,
        storage or _memory,
        get_settings(),
        io.BytesIO(HAR),
        org_id=org,
        source_kind="upload",
        filename="f.har",
    )


class IndexWriteFails(MemoryStorage):
    """Storage that accepts the redacted file and then fails on the index."""

    def __init__(self) -> None:
        super().__init__()
        self.objects = _memory.objects
        self.modified = _memory.modified

    def writer(self, key: str) -> Any:
        if key.endswith("/index.bin"):
            raise ConnectionError("storage went away")
        return super().writer(key)


def test_storage_failing_after_the_first_write_leaves_nothing(admin: Any) -> None:
    org = org_of(admin)
    before = objects()
    with session_scope() as db, pytest.raises(ConnectionError):
        run_intake(db, org, IndexWriteFails())
    assert objects() == before
    with session_scope() as db:
        assert db.scalars(select(Artifact)).all() == []


def test_the_database_failing_at_flush_leaves_nothing(admin: Any, monkeypatch: Any) -> None:
    org = org_of(admin)
    before = objects()
    with session_scope() as db:

        def broken_flush(*_: Any, **__: Any) -> None:
            raise OperationalError("INSERT", {}, Exception("server closed the connection"))

        monkeypatch.setattr(db, "flush", broken_flush)
        with pytest.raises(OperationalError):
            run_intake(db, org)
        monkeypatch.undo()
    assert objects() == before


def test_the_transaction_failing_at_commit_leaves_nothing(admin: Any) -> None:
    """The rows were flushed, then the commit failed (here: the caller rolls back, as
    every caller does when commit raises)."""
    org = org_of(admin)
    before = objects()
    with session_scope() as db:
        analysis = run_intake(db, org)
        key = analysis.artifact.storage_key
        assert key in _memory.objects and index_key(key) in _memory.objects
        db.rollback()
    assert objects() == before


def test_a_request_that_fails_after_intake_leaves_nothing(admin: Any, monkeypatch: Any) -> None:
    """The upload route stored the file, then something after intake raised before the
    commit; the request's session is closed without committing."""
    from hartriage.api import uploads

    def broken(*_: Any, **__: Any) -> None:
        raise RuntimeError("audit table unavailable")

    before = objects()
    monkeypatch.setattr(uploads.audit, "record", broken)  # type: ignore[attr-defined]
    with pytest.raises(RuntimeError):
        admin.upload(HAR, "f.har")
    assert objects() == before


def test_a_committed_upload_keeps_its_objects(admin: Any) -> None:
    org = org_of(admin)
    with session_scope() as db:
        key = run_intake(db, org).artifact.storage_key
    assert key in _memory.objects and index_key(key) in _memory.objects


def test_the_reconciler_deletes_old_objects_with_no_row_and_spares_the_rest(
    admin: Any,
) -> None:
    """A process killed between writing and committing leaves objects no row owns."""
    org = org_of(admin)
    with session_scope() as db:
        kept = run_intake(db, org).artifact.storage_key
    old_orphan = f"orgs/{org}/artifacts/{uuid.uuid4()}/redacted.har"
    in_flight = f"orgs/{org}/artifacts/{uuid.uuid4()}/redacted.har"
    for key in (old_orphan, index_key(old_orphan), in_flight):
        with _memory.writer(key) as w:
            w.write(b"{}")
    for key in (old_orphan, index_key(old_orphan)):
        _memory.modified[key] = datetime.now(UTC) - timedelta(hours=7)

    with session_scope() as db:
        counts = reconcile(db, _memory)
    assert counts["orphans"] == 2
    assert old_orphan not in _memory.objects and index_key(old_orphan) not in _memory.objects
    assert in_flight in _memory.objects  # young: may still be an upload in progress
    assert kept in _memory.objects and index_key(kept) in _memory.objects


def test_the_reconciler_removes_objects_of_a_purged_artifact(admin: Any) -> None:
    """Deleting a file whose storage delete failed: the row says deleted, the bytes stayed."""
    org = org_of(admin)
    with session_scope() as db:
        analysis = run_intake(db, org)
        key = analysis.artifact.storage_key
        analysis.artifact.deleted_at = datetime.now(UTC)
        analysis.artifact.storage_key = None
    with session_scope() as db:
        reconcile(db, _memory)
    assert key not in _memory.objects and index_key(key) not in _memory.objects
