"""What the worker needs from a helpdesk, whichever one it is."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import IO, Any
from urllib.parse import urlsplit

import httpx

from hartriage.core.metrics import HELPDESK_CALLS

SUBDOMAIN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
HAR_NAME = re.compile(r"\.(har|har\.gz|har\.zip|zip)$", re.IGNORECASE)


class HelpdeskError(Exception):
    """A helpdesk call failed. The message is safe to show to an admin."""


class RateLimited(HelpdeskError):
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited, retry after {retry_after:.0f} s")
        self.retry_after = retry_after


class AuthFailed(HelpdeskError):
    pass


@dataclass(frozen=True)
class Attachment:
    id: str
    filename: str
    size: int
    content_type: str
    url: str
    comment_id: str | None = None

    @property
    def is_har(self) -> bool:
        return bool(HAR_NAME.search(self.filename))


@dataclass
class Ticket:
    id: str
    subject: str
    tags: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)


def retry_after(response: httpx.Response) -> float:
    value = response.headers.get("retry-after", "")
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
        from datetime import UTC, datetime

        return max(1.0, (when - datetime.now(UTC)).total_seconds())
    except (TypeError, ValueError):
        return 60.0


class HelpdeskClient(ABC):
    platform: str
    allowed_download_hosts: tuple[str, ...] = ()

    def __init__(
        self,
        base_url: str,
        auth: httpx.Auth | None,
        headers: dict[str, str],
        timeout: float,
        transport: httpx.BaseTransport | None = None,
        trust_any_download_host: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.trust_any_download_host = trust_any_download_host
        self.http = httpx.Client(
            base_url=self.base_url,
            auth=auth,
            headers=headers,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
        )

    def close(self) -> None:
        self.http.close()

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self.http.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            HELPDESK_CALLS.labels(self.platform, "network_error").inc()
            raise HelpdeskError(
                f"{self.platform} could not be reached ({type(exc).__name__})"
            ) from exc
        HELPDESK_CALLS.labels(self.platform, str(response.status_code)).inc()
        if response.status_code == 429:
            raise RateLimited(retry_after(response))
        if response.status_code in (401, 403):
            raise AuthFailed(f"{self.platform} refused the credentials ({response.status_code})")
        if response.status_code >= 400:
            raise HelpdeskError(
                f"{self.platform} answered {response.status_code} for {method} {urlsplit(url).path}"
            )
        return response

    def check_download_url(self, url: str) -> None:
        """Only follow attachment links to the helpdesk's own hosts (no SSRF via ticket content)."""
        parts = urlsplit(url)
        if self.trust_any_download_host:
            return
        host = (parts.hostname or "").lower()
        if parts.scheme != "https" or not any(
            host == h or host.endswith("." + h) for h in self.allowed_download_hosts
        ):
            raise HelpdeskError(
                f"refusing to download an attachment from {host or 'an unknown host'}"
            )

    @contextmanager
    def open_attachment(self, attachment: Attachment, max_bytes: int) -> Iterator[IO[bytes]]:
        """Stream an attachment. Redirects are followed by hand so every hop is checked;
        the API credentials are only ever sent to the helpdesk's own API host."""
        url = attachment.url
        for _ in range(5):
            self.check_download_url(url)
            same_host = urlsplit(url).netloc == urlsplit(self.base_url).netloc
            client = (
                self.http
                if same_host
                else httpx.Client(timeout=self.http.timeout, transport=self.http._transport)
            )
            request = client.build_request("GET", url)
            response = client.send(request, stream=True)
            if response.is_redirect and "location" in response.headers:
                url = str(httpx.URL(url).join(response.headers["location"]))
                response.close()
                continue
            if response.status_code == 429:
                response.close()
                raise RateLimited(retry_after(response))
            if response.status_code >= 400:
                response.close()
                raise HelpdeskError(f"attachment download failed ({response.status_code})")
            declared = response.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > max_bytes:
                response.close()
                raise HelpdeskError("attachment is larger than the upload limit")
            try:
                yield _ResponseReader(response)  # type: ignore[misc]
            finally:
                response.close()
            return
        raise HelpdeskError("too many redirects while downloading the attachment")

    # -- the platform-specific part ------------------------------------------------

    @abstractmethod
    def verify(self) -> str:
        """Check the credentials; return the account's display name."""

    @abstractmethod
    def get_ticket(self, ticket_id: str) -> Ticket: ...

    @abstractmethod
    def post_private_note(
        self, ticket: Ticket, html: str, attachment: tuple[str, bytes] | None
    ) -> str:
        """Post a private note; return its id on the helpdesk."""

    @abstractmethod
    def find_note(self, ticket_id: str, marker: str) -> str | None:
        """The id of an existing note containing `marker`, if one was already posted."""

    @abstractmethod
    def swap_tags(self, ticket: Ticket, remove: str, add: str) -> None: ...

    @abstractmethod
    def remove_attachment(self, ticket: Ticket, attachment: Attachment) -> None:
        """Remove the original (unredacted) attachment from the ticket."""


class _ResponseReader:
    def __init__(self, response: httpx.Response) -> None:
        self._iter = response.iter_bytes(64 * 1024)  # undoes Content-Encoding
        self._buffer = b""

    def read(self, size: int = -1) -> bytes:
        if size == 0:
            return b""
        while size < 0 or len(self._buffer) < size:
            try:
                self._buffer += next(self._iter)
            except StopIteration:
                break
        if size < 0:
            data, self._buffer = self._buffer, b""
        else:
            data, self._buffer = self._buffer[:size], self._buffer[size:]
        return data
