"""Build a client for a stored connection. Credentials are decrypted only here."""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from hartriage.core.config import Settings
from hartriage.core.security import Cipher
from hartriage.db.models import HelpdeskConnection
from hartriage.helpdesk.base import HelpdeskClient
from hartriage.helpdesk.freshdesk import FreshdeskClient
from hartriage.helpdesk.zendesk import ZendeskClient

# Tests swap in a factory of transports that talk to the fake helpdesk in-process.
# A factory, not one shared transport: every client closes its transport when
# done, and a shared one would be closed under the other threads' requests.
TEST_TRANSPORT: Callable[[], httpx.BaseTransport] | None = None


def cipher(settings: Settings) -> Cipher:
    return Cipher(settings.encryption_key_bytes)


def credentials(settings: Settings, conn: HelpdeskConnection) -> dict[str, str]:
    data: dict[str, str] = json.loads(
        cipher(settings).decrypt(conn.credentials_encrypted, str(conn.id))
    )
    return data


def webhook_secret(settings: Settings, conn: HelpdeskConnection) -> str:
    return cipher(settings).decrypt(conn.webhook_secret_encrypted, f"webhook:{conn.id}")


def base_url(settings: Settings, platform: str, subdomain: str) -> str | None:
    if settings.helpdesk_base_url_override:
        return f"{settings.helpdesk_base_url_override.rstrip('/')}/{platform}/{subdomain}"
    return None


def client_for(
    settings: Settings, platform: str, subdomain: str, creds: dict[str, str]
) -> HelpdeskClient:
    url = base_url(settings, platform, subdomain)
    timeout = settings.helpdesk_timeout_seconds
    transport = TEST_TRANSPORT() if TEST_TRANSPORT is not None else None
    if platform == "zendesk":
        return ZendeskClient.build(subdomain, creds, timeout, url, transport)
    return FreshdeskClient.build(subdomain, creds, timeout, url, transport)


def client(settings: Settings, conn: HelpdeskConnection) -> HelpdeskClient:
    return client_for(settings, conn.platform, conn.subdomain, credentials(settings, conn))
