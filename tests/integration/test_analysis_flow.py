from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select, update

from tests.integration.conftest import member, register
from tests.support.har import entry, har, headers, make_jwt

pytestmark = pytest.mark.integration
GOLDEN = Path(__file__).resolve().parents[1] / "golden" / "hars"
SECRET = "sk" + "_live_" + "Zx9" * 8  # assembled at run time


def checkout() -> bytes:
    return (GOLDEN / "chromium" / "checkout-story.har").read_bytes()


def secret_har() -> bytes:
    token = make_jwt(exp=1_000_000_000)
    return json.dumps(
        har(
            entry(
                "https://app.example.com/",
                resource_type="document",
                content={"size": 10, "mimeType": "text/html", "text": "<html>secret page</html>"},
            ),
            entry(
                f"https://api.example.com/v1/me?api_key={SECRET}",
                status=401,
                started="2026-11-14T10:00:01.000Z",
                request_headers=headers(Authorization=f"Bearer {token}", Cookie=f"sid={SECRET}"),
                response_headers=headers(X_Request_Id="req-abc"),
            ),
        )
    ).encode()


def test_upload_analyse_and_read_back(client: Any, admin: Any) -> None:
    response = admin.upload(checkout(), "checkout.har")
    assert response.status_code == 202, response.text
    analysis_id = response.json()["analysis_id"]
    detail = admin.get(f"/v1/analyses/{analysis_id}").json()
    assert detail["status"] == "done", detail
    assert detail["engine_version"] and detail["entry_count"] == 7
    assert detail["summary"]["lead_rule"] == "R002"
    assert "Removed 1 token" in detail["redaction"]["sentence"]
    assert detail["source"] == {"kind": "upload"}

    findings = admin.get(f"/v1/analyses/{analysis_id}/findings").json()["items"]
    assert [f["rule_id"] for f in findings][:2] == ["R001", "R002"]
    assert findings[1]["kb"] == "R002-auth"

    entries = admin.get(f"/v1/analyses/{analysis_id}/entries").json()
    assert len(entries["items"]) == 7 and entries["hosts"][0]["host"] == "app.test"
    failed = admin.get(f"/v1/analyses/{analysis_id}/entries", params={"status": "failed"}).json()[
        "items"
    ]
    assert {e["status"] for e in failed} == {401, 500}
    slow = admin.get(f"/v1/analyses/{analysis_id}/entries", params={"min_ms": 3000}).json()["items"]
    assert [e["number"] for e in slow] == [6]

    one = admin.get(f"/v1/analyses/{analysis_id}/entries/3").json()
    auth = next(
        h["value"]
        for h in one["entry"]["request"]["headers"]
        if h["name"].lower() == "authorization"
    )
    assert auth.startswith("Bearer [REDACTED:")
    assert one["meta"]["credentials"] == ["authorization:bearer"]

    md = admin.get(f"/v1/analyses/{analysis_id}/export", params={"format": "md"})
    assert md.status_code == 200 and "**Likely cause:**" in md.text
    js = admin.get(f"/v1/analyses/{analysis_id}/export", params={"format": "json"}).json()
    assert js["findings"][0]["rule_id"] == "R001"

    history = admin.get("/v1/analyses").json()["items"]
    assert history[0]["id"] == analysis_id and history[0]["filename"] == "checkout.har"

    actions = [a["action"] for a in admin.get("/v1/audit").json()["items"]]
    assert {"analysis.uploaded", "analysis.viewed", "analysis.exported"} <= set(actions)


def test_raw_upload_is_never_stored(client: Any, admin: Any) -> None:
    from hartriage.storage.s3 import _memory

    response = admin.upload(secret_har())
    analysis_id = response.json()["analysis_id"]
    stored = b"".join(_memory.objects.values())
    assert SECRET.encode() not in stored and b"secret page" not in stored
    assert len(_memory.objects) == 2  # the redacted file and its offsets index, nothing else
    download = admin.get(f"/v1/analyses/{analysis_id}/redacted.har")
    assert download.status_code == 200 and SECRET not in download.text
    assert json.loads(download.text)["log"]["entries"][1]["_hartriage"]["correlation_ids"] == {
        "x-request-id": "req-abc"
    }


def test_gzip_upload(client: Any, admin: Any) -> None:
    response = admin.upload(gzip.compress(checkout()), "checkout.har.gz")
    assert response.status_code == 202
    assert admin.get(f"/v1/analyses/{response.json()['analysis_id']}").json()["status"] == "done"


def test_bad_uploads_get_plain_errors(client: Any, admin: Any) -> None:
    from hartriage.storage.s3 import _memory

    bad = admin.upload(b"this is not json")
    assert bad.status_code == 422
    assert bad.json()["error"] == {
        **bad.json()["error"],
        "code": "invalid_har",
        "message": "Not a valid HAR file: it is not JSON.",
    }
    missing = admin.upload(b'{"log": {"version": "1.2"}}')
    assert missing.json()["error"]["message"] == "Not a valid HAR file: missing log.entries."
    assert _memory.objects == {}  # a failed upload leaves nothing behind


def test_upload_limit(client: Any, admin: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARTRIAGE_MAX_UPLOAD_BYTES", "2000")
    from hartriage.core.config import get_settings

    get_settings.cache_clear()
    response = admin.upload(checkout())
    assert response.status_code == 413 and response.json()["error"]["code"] == "too_large"


def test_rerun_uses_the_stored_file(client: Any, admin: Any) -> None:
    analysis_id = admin.upload(checkout()).json()["analysis_id"]
    first = admin.get(f"/v1/analyses/{analysis_id}/findings").json()["items"]
    assert admin.post(f"/v1/analyses/{analysis_id}/rerun").status_code == 202
    again = admin.get(f"/v1/analyses/{analysis_id}/findings").json()["items"]
    assert [f["title"] for f in again] == [f["title"] for f in first]


def test_tenancy(client: Any, admin: Any) -> None:
    analysis_id = admin.upload(checkout()).json()["analysis_id"]
    other = register(client, "other@example.org", "Other Co")
    for path in ("", "/findings", "/entries", "/entries/1", "/export", "/redacted.har"):
        response = other.get(f"/v1/analyses/{analysis_id}{path}")
        assert response.status_code == 404, path
    assert other.post(f"/v1/analyses/{analysis_id}/rerun").status_code == 404
    assert other.get("/v1/analyses").json()["items"] == []


def test_viewer_can_read_but_not_download_or_delete(client: Any, admin: Any) -> None:
    analysis_id = admin.upload(checkout()).json()["analysis_id"]
    viewer = member(client, admin, "viewer@example.com", "viewer")
    assert viewer.get(f"/v1/analyses/{analysis_id}").status_code == 200
    assert viewer.get(f"/v1/analyses/{analysis_id}/redacted.har").status_code == 403
    assert viewer.delete(f"/v1/analyses/{analysis_id}").status_code == 403


def test_expired_analysis_is_deleted_from_database_and_storage(client: Any, admin: Any) -> None:
    from hartriage.core.config import get_settings
    from hartriage.db.models import Analysis, Artifact, EntryIndex, FindingRow
    from hartriage.db.session import session_scope
    from hartriage.services.retention import sweep
    from hartriage.storage.s3 import get_storage

    analysis_id = admin.upload(checkout()).json()["analysis_id"]
    storage = get_storage(get_settings())
    with session_scope() as db:
        assert (db.scalar(select(func.count()).select_from(FindingRow)) or 0) > 0
        db.execute(update(Artifact).values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    with session_scope() as db:
        assert sweep(db, storage) == 1
    with session_scope() as db:
        assert db.scalar(select(func.count()).select_from(Analysis)) == 0
        assert db.scalar(select(func.count()).select_from(FindingRow)) == 0
        assert db.scalar(select(func.count()).select_from(EntryIndex)) == 0
        tombstone = db.scalars(select(Artifact)).one()
        assert (
            tombstone.deleted_at
            and tombstone.storage_key is None
            and tombstone.original_filename is None
        )
    assert storage.objects == {}  # type: ignore[attr-defined]
    assert admin.get(f"/v1/analyses/{analysis_id}").status_code == 404
    with session_scope() as db:
        assert sweep(db, storage) == 0  # nothing left to do


def test_admin_delete(client: Any, admin: Any) -> None:
    analysis_id = admin.upload(checkout()).json()["analysis_id"]
    assert admin.delete(f"/v1/analyses/{analysis_id}").status_code == 204
    assert admin.get(f"/v1/analyses/{analysis_id}").status_code == 404


def test_kb_and_health(client: Any) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = client.get("/readyz").json()
    assert ready["checks"]["database"] == "ok"
    index = client.get("/v1/kb").json()["items"]
    assert len(index) == 12
    article = client.get("/v1/kb/R002-auth")
    assert article.status_code == 200 and article.text.startswith("# R002")
    assert client.get("/v1/kb/..%2F..%2Fpyproject").status_code == 404
    assert "hartriage_uploads_total" in client.get("/metrics").text
