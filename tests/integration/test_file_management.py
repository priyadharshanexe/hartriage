"""File management: who sees, deletes and is limited on which files.

Agents and viewers see only the files they uploaded; admins see every file in the
organisation, including files that came from helpdesk tickets (which have no uploader).
Someone else's file is "not found", never "forbidden".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import update

from tests.integration.conftest import member

pytestmark = pytest.mark.integration
HAR = (
    Path(__file__).resolve().parents[1] / "golden" / "hars" / "chromium" / "checkout-story.har"
).read_bytes()


def upload(api: Any, name: str = "mine.har") -> str:
    response = api.upload(HAR, name)
    assert response.status_code == 202, response.text
    return str(response.json()["analysis_id"])


ROUTES = [
    ("get", "/v1/analyses/{id}"),
    ("get", "/v1/analyses/{id}/findings"),
    ("get", "/v1/analyses/{id}/entries"),
    ("get", "/v1/analyses/{id}/entries/1"),
    ("get", "/v1/analyses/{id}/export?format=md"),
    ("get", "/v1/analyses/{id}/redacted.har"),
    ("post", "/v1/analyses/{id}/rerun"),
    ("delete", "/v1/analyses/{id}"),
]


@pytest.mark.parametrize(("method", "route"), ROUTES)
def test_an_agent_cannot_reach_another_agents_file(
    client: Any, admin: Any, method: str, route: str
) -> None:
    alice = member(client, admin, "alice@example.com", "agent")
    bob = member(client, admin, "bob@example.com", "agent")
    viewer = member(client, admin, "vic@example.com", "viewer")
    analysis_id = upload(alice)
    url = route.format(id=analysis_id)
    assert getattr(bob, method)(url).status_code == 404
    if method == "get":
        # Viewers can't download redacted HARs at all (by role), so that one is 403.
        assert getattr(viewer, method)(url).status_code in ((403,) if "redacted" in url else (404,))
        assert getattr(alice, method)(url).status_code == 200
        assert getattr(admin, method)(url).status_code == 200


def test_history_lists_own_files_for_agents_and_all_for_admins(client: Any, admin: Any) -> None:
    alice = member(client, admin, "alice@example.com", "agent")
    bob = member(client, admin, "bob@example.com", "agent")
    a = upload(alice, "alice.har")
    b = upload(bob, "bob.har")
    mine = upload(admin, "admin.har")

    def ids(api: Any, q: str = "") -> set[str]:
        return {i["id"] for i in api.get(f"/v1/analyses{q}").json()["items"]}

    assert ids(alice) == {a}
    assert ids(alice, "?scope=all") == {a}  # an agent can't widen the scope
    assert ids(bob) == {b}
    assert ids(admin) == {a, b, mine}
    assert ids(admin, "?scope=mine") == {mine}
    item = next(i for i in admin.get("/v1/analyses").json()["items"] if i["id"] == a)
    assert item["uploaded_by"]["email"] == "alice@example.com"
    assert ids(admin, "?source=ticket") == set()
    assert ids(admin, "?status=failed") == set()


def test_ticket_files_are_admin_only(client: Any, admin: Any) -> None:
    from hartriage.db.models import Analysis, Artifact
    from hartriage.db.session import session_scope

    alice = member(client, admin, "alice@example.com", "agent")
    analysis_id = upload(admin, "from-ticket.har")
    with session_scope() as db:  # make it look like a helpdesk file: no uploader
        db.execute(update(Analysis).where(Analysis.id == analysis_id).values(created_by=None))
        art = db.get(Analysis, analysis_id).artifact.id  # type: ignore[union-attr]
        db.execute(update(Artifact).where(Artifact.id == art).values(source="ticket"))
        db.commit()
    assert alice.get(f"/v1/analyses/{analysis_id}").status_code == 404
    assert alice.delete(f"/v1/analyses/{analysis_id}").status_code == 404
    assert admin.get(f"/v1/analyses/{analysis_id}").json()["uploaded_by"] is None
    assert admin.delete(f"/v1/analyses/{analysis_id}").status_code == 204


def test_agents_delete_their_own_files_and_it_is_audited(client: Any, admin: Any) -> None:
    alice = member(client, admin, "alice@example.com", "agent")
    viewer = member(client, admin, "vic@example.com", "viewer")
    analysis_id = upload(alice)
    assert viewer.delete(f"/v1/analyses/{analysis_id}").status_code in (403, 404)
    assert alice.delete(f"/v1/analyses/{analysis_id}").status_code == 204
    assert alice.get(f"/v1/analyses/{analysis_id}").status_code == 404
    assert alice.get("/v1/analyses").json()["items"] == []
    actions = [e["action"] for e in admin.get("/v1/audit").json()["items"]]
    assert "artifact.deleted" in actions


def test_admins_bulk_delete(client: Any, admin: Any) -> None:
    alice = member(client, admin, "alice@example.com", "agent")
    ids = [upload(alice, f"f{i}.har") for i in range(3)]
    assert alice.post("/v1/analyses/bulk-delete", json={"ids": ids}).status_code == 403
    result = admin.post("/v1/analyses/bulk-delete", json={"ids": [*ids[:2], ids[0]]})
    assert result.json() == {"deleted": 2}
    assert {i["id"] for i in admin.get("/v1/analyses").json()["items"]} == {ids[2]}


def test_org_limits_are_enforced_on_upload(client: Any, admin: Any) -> None:
    alice = member(client, admin, "alice@example.com", "agent")
    assert alice.put("/v1/org/settings", json={"retention_days": 7}).status_code == 403
    assert admin.put("/v1/org/settings", json={"retention_days": 14}).status_code == 422
    assert (
        admin.put(
            "/v1/org/settings", json={"retention_days": 30, "max_file_mb": 100000}
        ).status_code
        == 422
    )

    # Retention applies to new uploads.
    assert admin.put("/v1/org/settings", json={"retention_days": 7}).status_code == 200
    first = upload(alice)
    expires = alice.get(f"/v1/analyses/{first}").json()["expires_at"]
    created = alice.get(f"/v1/analyses/{first}").json()["created_at"]
    from datetime import datetime

    days = (datetime.fromisoformat(expires) - datetime.fromisoformat(created)).days
    assert 6 <= days <= 7

    # Daily uploads per member.
    admin.put("/v1/org/settings", json={"retention_days": 30, "daily_uploads_per_member": 1})
    refused = alice.upload(HAR, "second.har")
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "daily_upload_limit"

    # Storage quota (1 MB, and the file is already stored).
    admin.put("/v1/org/settings", json={"retention_days": 30, "storage_quota_mb": 1})
    big = b" " * (1024 * 1024) + HAR
    refused = admin.upload(big, "big.har")
    assert refused.status_code == 413
    assert refused.json()["error"]["code"] == "storage_quota_exceeded"

    # Max file size.
    admin.put("/v1/org/settings", json={"retention_days": 30, "max_file_mb": 1})
    assert admin.upload(big, "big.har").status_code == 413


def test_usage_by_member(client: Any, admin: Any) -> None:
    alice = member(client, admin, "alice@example.com", "agent")
    upload(alice)
    upload(alice, "two.har")
    usage = admin.get("/v1/org/usage").json()
    row = next(m for m in usage["members"] if m["email"] == "alice@example.com")
    assert row["files"] == 2 and row["bytes"] > 0
    assert usage["storage_used_bytes"] >= row["bytes"]
    assert alice.get("/v1/org/usage").status_code == 403
    assert alice.get("/v1/org/settings").json()["uploads_today"] == 2
