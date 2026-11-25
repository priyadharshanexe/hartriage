"""What happens when a dependency fails at each step, and whether a retry converges."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from kombu.exceptions import OperationalError as BrokerDown

pytestmark = pytest.mark.integration
HAR = (
    Path(__file__).resolve().parents[1] / "golden" / "hars" / "chromium" / "checkout-story.har"
).read_bytes()


def test_broker_down_at_enqueue_keeps_the_upload_and_a_sweep_finishes_it(
    admin: Any, monkeypatch: Any
) -> None:
    """Redis is down after the upload committed. The file is safe and the user is told
    it is queued (not a 500); the requeue sweep sends it once the broker is back."""
    from hartriage.api import uploads
    from hartriage.db.models import Analysis
    from hartriage.db.session import session_scope
    from hartriage.worker.tasks import requeue_stale

    def broker_down(*_: Any) -> None:
        raise BrokerDown("Error 111 connecting to redis:6379. Connection refused.")

    monkeypatch.setattr(uploads, "enqueue_analysis", broker_down)
    response = admin.upload(HAR, "queued.har")
    assert response.status_code == 202, response.text
    analysis_id = response.json()["analysis_id"]
    assert admin.get(f"/v1/analyses/{analysis_id}").json()["status"] == "queued"
    monkeypatch.undo()

    assert requeue_stale.apply().get() == 0  # too recent: its task may still be on its way
    with session_scope() as db:
        row = db.get(Analysis, analysis_id)
        assert row is not None
        row.created_at = datetime.now(UTC) - timedelta(minutes=10)
    assert requeue_stale.apply().get() == 1
    assert admin.get(f"/v1/analyses/{analysis_id}").json()["status"] == "done"


def test_storage_down_on_read_fails_then_a_retry_converges(admin: Any, monkeypatch: Any) -> None:
    """S3 is unreachable when the worker reads the file back: the analysis is marked
    failed with a retry hint and the task raises (Celery retries it). Re-running once
    storage is back produces the same result as if nothing had happened."""
    from hartriage.services import analysis as analysis_service
    from hartriage.worker.dispatch import enqueue_analysis

    real = analysis_service.load_offsets  # type: ignore[attr-defined]

    def storage_down(*_: Any) -> Any:
        raise ConnectionError("storage unreachable")

    analysis_id = admin.upload(HAR, "s3-down.har").json()["analysis_id"]
    monkeypatch.setattr(analysis_service, "load_offsets", storage_down)
    with pytest.raises(ConnectionError):
        enqueue_analysis(analysis_id)  # the worker's run: it raises, so Celery retries
    failed = admin.get(f"/v1/analyses/{analysis_id}").json()
    assert failed["status"] == "failed" and "re-running" in failed["error"]

    monkeypatch.setattr(analysis_service, "load_offsets", real)
    enqueue_analysis(analysis_id)  # Celery's retry
    done = admin.get(f"/v1/analyses/{analysis_id}").json()
    assert done["status"] == "done" and done["error"] is None
    findings = admin.get(f"/v1/analyses/{analysis_id}/findings").json()["items"]
    assert findings and findings[0]["rule_id"] == "R001"


def test_a_task_run_twice_gives_one_set_of_results(admin: Any) -> None:
    """A worker killed mid-task: acks_late redelivers it, and the re-run starts over."""
    from hartriage.worker.dispatch import enqueue_analysis

    analysis_id = admin.upload(HAR, "twice.har").json()["analysis_id"]

    def findings() -> list[dict[str, Any]]:
        items = admin.get(f"/v1/analyses/{analysis_id}/findings").json()["items"]
        return [{k: v for k, v in f.items() if k != "id"} for f in items]  # ids are new rows

    first = findings()
    entries = admin.get(f"/v1/analyses/{analysis_id}/entries").json()["items"]
    enqueue_analysis(analysis_id)
    assert findings() == first
    assert admin.get(f"/v1/analyses/{analysis_id}/entries").json()["items"] == entries


def test_an_analysis_stuck_running_is_sent_again(admin: Any) -> None:
    """The worker died and its message was lost (or Postgres was down when it tried to
    record the failure): the row says "running" long after any task could be."""
    from hartriage.db.models import Analysis
    from hartriage.db.session import session_scope
    from hartriage.worker.tasks import requeue_stale

    analysis_id = admin.upload(HAR, "stuck.har").json()["analysis_id"]
    with session_scope() as db:
        row = db.get(Analysis, analysis_id)
        assert row is not None
        row.status, row.finished_at = "running", None
        row.started_at = datetime.now(UTC) - timedelta(hours=3)
    assert requeue_stale.apply().get() == 1
    assert admin.get(f"/v1/analyses/{analysis_id}").json()["status"] == "done"
