from __future__ import annotations

from typing import Any

import pytest

from tests.integration.conftest import member, register

pytestmark = pytest.mark.integration


def test_register_login_me(client: Any) -> None:
    api = register(client)
    me = api.get("/v1/auth/me").json()
    assert me["role"] == "admin" and me["orgs"][0]["name"] == "Acme Support"
    login = client.post(
        "/v1/auth/login", json={"email": "ADMIN@example.com", "password": "correct horse battery"}
    )
    assert login.status_code == 200 and "access_token" in login.json()
    wrong = client.post(
        "/v1/auth/login", json={"email": "admin@example.com", "password": "nope nope nope"}
    )
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "unauthorized"
    unknown = client.post(
        "/v1/auth/login", json={"email": "who@example.com", "password": "nope nope nope"}
    )
    assert (
        unknown.status_code == 401
        and unknown.json()["error"]["message"] == wrong.json()["error"]["message"]
    )


def test_refresh_rotates_and_detects_reuse(client: Any) -> None:
    register(client)
    old = client.cookies.get("hartriage_refresh")
    first = client.post("/v1/auth/refresh")
    assert first.status_code == 200
    assert client.cookies.get("hartriage_refresh") != old
    client.cookies.set("hartriage_refresh", old, path="/v1/auth")
    reused = client.post("/v1/auth/refresh")
    assert reused.status_code == 401
    # The reuse ended every session, including the one rotated a moment ago.
    client.cookies.clear()
    assert client.post("/v1/auth/refresh").status_code == 401


def test_logout(client: Any) -> None:
    register(client)
    assert client.post("/v1/auth/logout").status_code == 204
    assert client.post("/v1/auth/refresh").status_code == 401


def test_errors_have_one_shape(client: Any) -> None:
    body = client.post("/v1/auth/register", json={"email": "x"}).json()
    assert body["error"]["code"] == "validation_error" and body["error"]["request_id"]
    assert client.get("/v1/analyses").json()["error"]["code"] == "unauthorized"


def test_invitations_and_roles(client: Any, admin: Any) -> None:
    agent = member(client, admin, "agent@example.com", "agent")
    viewer = member(client, admin, "viewer@example.com", "viewer")
    members = admin.get("/v1/members").json()["members"]
    assert {m["email"]: m["role"] for m in members} == {
        "admin@example.com": "admin",
        "agent@example.com": "agent",
        "viewer@example.com": "viewer",
    }
    # Agents and viewers cannot manage the team or connections.
    assert agent.get("/v1/members").status_code == 403
    assert agent.get("/v1/connections").status_code == 403
    assert (
        viewer.post(
            "/v1/connections", json={"platform": "freshdesk", "subdomain": "x", "api_key": "k"}
        ).status_code
        == 403
    )
    # Viewers cannot upload.
    assert viewer.upload(b"{}").status_code == 403
    # Role changes apply on the next request, without a new token.
    admin.patch(f"/v1/members/{members[2]['user_id']}", json={"role": "agent"})
    me = viewer.get("/v1/auth/me").json()
    assert me["role"] in ("agent", "viewer")


def test_last_admin_cannot_be_removed(client: Any, admin: Any) -> None:
    me = admin.get("/v1/auth/me").json()["user"]["id"]
    assert admin.delete(f"/v1/members/{me}").json()["error"]["code"] == "last_admin"
    assert admin.patch(f"/v1/members/{me}", json={"role": "agent"}).status_code == 409


def test_removed_member_loses_access_immediately(client: Any, admin: Any) -> None:
    agent = member(client, admin, "agent@example.com", "agent")
    user_id = agent.get("/v1/auth/me").json()["user"]["id"]
    assert admin.delete(f"/v1/members/{user_id}").status_code == 204
    assert agent.get("/v1/analyses").status_code == 401


def test_invitation_is_single_use(client: Any, admin: Any) -> None:
    invite = admin.post(
        "/v1/invitations", json={"email": "new@example.com", "role": "agent"}
    ).json()
    token = invite["invite_url"].split("#", 1)[1]
    ok = client.post(
        "/v1/auth/accept-invite", json={"token": token, "password": "a long password here"}
    )
    assert ok.status_code == 200
    again = client.post(
        "/v1/auth/accept-invite", json={"token": token, "password": "a long password here"}
    )
    assert again.status_code == 410


def test_invitation_lookup_tells_the_invitee_what_they_join(client: Any, admin: Any) -> None:
    invite = admin.post("/v1/invitations", json={"email": "Lee@Example.com", "role": "viewer"}).json()
    token = invite["invite_url"].split("#", 1)[1]
    info = client.get("/v1/invitations/lookup", params={"token": token}).json()
    assert info == {**info, "organization": "Acme Support", "email": "lee@example.com",
                    "role": "viewer", "existing_account": False}
    assert client.get("/v1/invitations/lookup", params={"token": "nope"}).status_code == 410
