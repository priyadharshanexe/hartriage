"""HAR Triage's Zendesk and Freshdesk clients against recorded traffic from real trials.

By default the cassettes in tests/cassettes are replayed: no network, no credentials,
so CI runs them on every push. To record them again against the live trials (this
creates a ticket, posts a private note and removes an attachment on each):

    HARTRIAGE_RECORD_LIVE=1 uv run pytest tests/contract -m live_helpdesk

Credentials come from .env.live (gitignored). Every request and response is scrubbed
before it is written (tests/contract/scrub.py), and the recording fails if a private
value survives.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
import vcr

from hartriage.helpdesk.base import HelpdeskClient, Ticket
from hartriage.helpdesk.freshdesk import FreshdeskClient
from hartriage.helpdesk.zendesk import ClientCredentials, ZendeskClient
from tests.contract import scrub

ROOT = Path(__file__).resolve().parents[2]
CASSETTES = ROOT / "tests" / "cassettes"
HAR = ROOT / "tests" / "golden" / "hars" / "chromium" / "auth.har"
RECORD = os.environ.get("HARTRIAGE_RECORD_LIVE") == "1"
MARKER = "HAR Triage contract test"
# Not the live trigger tag: nothing else on the trial accounts reacts to this one.
TAG, DONE = "har_contract", "har_contract_done"

pytestmark = [pytest.mark.live_helpdesk] if RECORD else []


def _live_env() -> dict[str, str]:
    from tools.live.env import load

    env = load()
    os.environ.update(
        {k: v for k, v in env.items() if k in ("ZENDESK_SUBDOMAIN", "FRESHDESK_DOMAIN")}
    )
    return env


def _recorder(name: str) -> Any:
    return vcr.VCR(
        cassette_library_dir=str(CASSETTES),
        record_mode="all" if RECORD else "none",
        match_on=["method", "scheme", "host", "path", "query"],
        filter_headers=scrub.SECRET_HEADERS,
        before_record_request=scrub.before_record_request,
        before_record_response=scrub.before_record_response,
        decode_compressed_response=True,
    ).use_cassette(f"{name}.yaml")


def _flow(client: HelpdeskClient, ticket_id: str, *, search: bool = False) -> dict[str, Any]:
    """Everything the worker does with a ticket, in order."""
    account = client.verify()
    if search:
        assert ticket_id in [t for t, _ in client.tagged_tickets(TAG)]
    ticket: Ticket = client.get_ticket(ticket_id)
    assert TAG in ticket.tags
    [har] = [a for a in ticket.attachments if a.is_har]
    with client.open_attachment(har, 100 * 1024 * 1024) as stream:
        content = stream.read()
    assert json.loads(content)["log"]["entries"]
    marker = f"{MARKER} {ticket_id}"
    note_id = client.post_private_note(
        ticket,
        f"<p>{marker}: findings would go here.</p>",
        ("auth.redacted.har", b'{\n"log":{"entries":[]}}'),
    )
    assert note_id
    assert client.find_note(ticket_id, marker) == note_id
    client.swap_tags(ticket, TAG, DONE)
    client.remove_attachment(ticket, har)
    after = client.get_ticket(ticket_id)
    assert DONE in after.tags and TAG not in after.tags
    return {"account": account, "har": har.filename}


# ------------------------------------------------------------------ Zendesk


def _zendesk_client(env: dict[str, str] | None) -> ZendeskClient:
    ClientCredentials._cache.clear()
    if env is None:  # replay
        creds = {"client_id": "hartriage_live_tests", "client_secret": "replayed"}
        return ZendeskClient.build("acme", creds, 30)
    creds = {
        "client_id": env["ZENDESK_OAUTH_CLIENT_ID"],
        "client_secret": env["ZENDESK_OAUTH_CLIENT_SECRET"],
    }
    return ZendeskClient.build(env["ZENDESK_SUBDOMAIN"], creds, 30)


def _zendesk_ticket(env: dict[str, str]) -> str:
    """A fresh tagged ticket with one HAR attached, made outside the recording."""
    from tools.live.zd_setup import zendesk

    with zendesk() as z:
        upload = z.post(
            "/api/v2/uploads.json",
            params={"filename": "auth.har"},
            content=HAR.read_bytes(),
            headers={"Content-Type": "application/json"},
        ).json()["upload"]["token"]
        ticket = z.post(
            "/api/v2/tickets.json",
            json={
                "ticket": {
                    "subject": "Contract test: sign-in fails (HAR attached)",
                    "requester": {"name": "HAR Tester", "email": "har.tester+contract@example.com"},
                    "tags": [TAG],
                    "comment": {"html_body": "<p>HAR attached.</p>", "uploads": [upload]},
                }
            },
        ).json()["ticket"]
    return str(ticket["id"])


def test_zendesk_client_against_a_real_account() -> None:
    use = scrub.sidecar(str(CASSETTES / "zendesk_flow.json"))
    if RECORD:
        env = _live_env()
        ticket_id = _zendesk_ticket(env)
        with _recorder("zendesk_flow"):
            result = _flow(_zendesk_client(env), ticket_id)
        use({"ticket_id": ticket_id, **{k: scrub.scrub_text(v) for k, v in result.items()}})
        scrub.assert_clean(str(CASSETTES / "zendesk_flow.yaml"), _forbidden(env))
    else:
        ticket_id = str(use(None)["ticket_id"])
        with _recorder("zendesk_flow"):
            result = _flow(_zendesk_client(None), ticket_id)
        assert result["har"] == "auth.har"


# ------------------------------------------------------------------ Freshdesk


def _freshdesk_client(env: dict[str, str] | None) -> FreshdeskClient:
    if env is None:
        return FreshdeskClient.build("acme", {"api_key": "replayed"}, 30)
    domain = env["FRESHDESK_DOMAIN"].replace("https://", "").split(".freshdesk.com")[0]
    return FreshdeskClient.build(domain, {"api_key": env["FRESHDESK_API_KEY"]}, 30)


def _freshdesk_ticket(env: dict[str, str]) -> str:
    domain = env["FRESHDESK_DOMAIN"].replace("https://", "").split(".freshdesk.com")[0]
    with httpx.Client(
        base_url=f"https://{domain}.freshdesk.com", auth=(env["FRESHDESK_API_KEY"], "X"), timeout=60
    ) as c:
        r = c.post(
            "/api/v2/tickets",
            data={
                "subject": "Contract test: sign-in fails (HAR attached)",
                "description": "<p>HAR attached.</p>",
                "email": "har.tester+contract@example.com",
                "status": "2",
                "priority": "1",
                "tags[]": TAG,
            },
            files=[("attachments[]", ("auth.har", HAR.read_bytes(), "application/json"))],
        )
        r.raise_for_status()
        ticket_id = str(r.json()["id"])
        # The search index lags behind a new ticket, and not every search replica
        # catches up at once: wait until three searches in a row find it.
        hits = 0
        for _ in range(60):
            found = c.get(
                "/api/v2/search/tickets", params={"query": f"\"tag:'{TAG}'\"", "page": 1}
            ).json()
            hits = (
                hits + 1 if any(str(t["id"]) == ticket_id for t in found.get("results", [])) else 0
            )
            if hits >= 3:
                break
            time.sleep(2)
    return ticket_id


def test_freshdesk_client_against_a_real_account() -> None:
    use = scrub.sidecar(str(CASSETTES / "freshdesk_flow.json"))
    if RECORD:
        env = _live_env()
        ticket_id = _freshdesk_ticket(env)
        with _recorder("freshdesk_flow"):
            result = _flow(_freshdesk_client(env), ticket_id, search=True)
        use({"ticket_id": ticket_id, **{k: scrub.scrub_text(v) for k, v in result.items()}})
        scrub.assert_clean(str(CASSETTES / "freshdesk_flow.yaml"), _forbidden(env))
    else:
        ticket_id = str(use(None)["ticket_id"])
        with _recorder("freshdesk_flow"):
            result = _flow(_freshdesk_client(None), ticket_id, search=True)
        assert result["har"] == "auth.har"


def _forbidden(env: dict[str, str]) -> list[str]:
    values = [
        env.get("FRESHDESK_API_KEY", ""),
        env.get("ZENDESK_OAUTH_CLIENT_SECRET", ""),
        env.get("ZENDESK_SUBDOMAIN", ""),
        env.get("FRESHDESK_DOMAIN", "").replace("https://", "").split(".")[0],
        *[w for w in os.environ.get("HARTRIAGE_SCRUB_WORDS", "").split(",") if w.strip()],
    ]
    return [v for v in values if len(v) >= 4]
