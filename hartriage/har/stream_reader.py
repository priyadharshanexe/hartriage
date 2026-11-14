"""Read a HAR file one entry at a time, so memory does not grow with the file size.

The reader accepts plain, gzip-compressed and zip-wrapped HAR files. Every size it
enforces (compressed bytes, decompressed bytes, entry count) raises
`InputTooLarge` with a message an agent can show to a customer.

What it keeps in memory: the entry being parsed, plus the small fields under
`log` that are not entries (version, creator, browser, pages, comment).
"""

from __future__ import annotations

import codecs
import gzip
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import IO, Any

import ijson

CHUNK = 64 * 1024


class HarFormatError(ValueError):
    """The input is not a HAR file. The message is safe to show to a user."""


class InputTooLarge(ValueError):
    """The input breaks a size limit. The message is safe to show to a user."""


@dataclass(frozen=True)
class Limits:
    max_bytes: int | None = 100 * 1024 * 1024  # bytes read from the source
    max_decompressed_bytes: int | None = 400 * 1024 * 1024
    max_entries: int | None = 50_000


NO_LIMITS = Limits(max_bytes=None, max_decompressed_bytes=None, max_entries=None)


class _CountingReader(io.RawIOBase):
    """Counts bytes read and stops reading once a limit is passed."""

    def __init__(self, raw: IO[bytes], limit: int | None, what: str) -> None:
        self._raw = raw
        self._limit = limit
        self._what = what
        self.count = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if size == 0:  # ijson probes with read(0) to learn whether it gets bytes or str
            return b""
        data = self._raw.read(size if size > 0 else CHUNK)
        self.count += len(data)
        if self._limit is not None and self.count > self._limit:
            raise InputTooLarge(f"the {self._what} is larger than {_human(self._limit)}")
        return data

    def readinto(self, buffer: Any) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


class _CleanUtf8(io.RawIOBase):
    """Re-encodes the stream as valid UTF-8: strips a BOM, replaces broken bytes.

    Browsers occasionally write bodies with invalid UTF-8 into a HAR file. A strict
    parser would reject the whole file for one bad byte in one response.
    """

    def __init__(self, raw: IO[bytes]) -> None:
        self._raw = raw
        self._decoder = codecs.getincrementaldecoder("utf-8-sig")(errors="replace")
        self._done = False

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        if size == 0:
            return b""
        while not self._done:
            chunk = self._raw.read(CHUNK)
            text = self._decoder.decode(chunk, final=not chunk)
            if not chunk:
                self._done = True
            if text:
                return text.encode("utf-8")
        return b""

    def readinto(self, buffer: Any) -> int:  # pragma: no cover - ijson calls read()
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


def _human(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.0f} MB"
    if n >= 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n} bytes"


def open_har_stream(source: IO[bytes], limits: Limits = Limits()) -> IO[bytes]:
    """Wrap `source` so it yields the decompressed, size-checked HAR JSON bytes."""
    counted = _CountingReader(source, limits.max_bytes, "upload")
    buffered = io.BufferedReader(counted, buffer_size=CHUNK)
    magic = buffered.peek(4)[:4]

    inner: IO[bytes]
    if magic[:2] == b"\x1f\x8b":
        inner = gzip.GzipFile(fileobj=buffered, mode="rb")  # type: ignore[assignment]
    elif magic == b"PK\x03\x04":
        inner = _open_zip_member(buffered)
    else:
        inner = buffered
    decompressed: IO[bytes] = _CountingReader(inner, limits.max_decompressed_bytes, "unpacked file")  # type: ignore[assignment]
    return _CleanUtf8(decompressed)  # type: ignore[return-value]


def _open_zip_member(stream: IO[bytes]) -> IO[bytes]:
    # A zip's directory is at its end, so the zip itself has to be in memory. Its
    # size is already capped by the upload limit; the member is still streamed.
    data = io.BytesIO(stream.read())
    try:
        archive = zipfile.ZipFile(data)
    except zipfile.BadZipFile as exc:
        raise HarFormatError("not a valid HAR file: the zip archive is damaged") from exc
    names = [n for n in archive.namelist() if n.lower().endswith(".har")]
    if len(names) != 1:
        raise HarFormatError(
            "not a valid HAR file: the zip archive must contain exactly one .har file"
            f" (found {len(names)})"
        )
    return archive.open(names[0])


@dataclass
class HarLog:
    """Everything under `log` except the entries, filled in while reading."""

    fields: dict[str, Any] = field(default_factory=dict)
    entry_count: int = 0
    truncated: bool = False

    @property
    def pages(self) -> list[dict[str, Any]]:
        pages = self.fields.get("pages")
        return pages if isinstance(pages, list) else []

    @property
    def creator(self) -> str:
        creator = self.fields.get("creator")
        if isinstance(creator, dict):
            name = str(creator.get("name", "")).strip()
            version = str(creator.get("version", "")).strip()
            return f"{name} {version}".strip()
        return ""

    @property
    def browser(self) -> str:
        browser = self.fields.get("browser")
        if isinstance(browser, dict):
            return f"{browser.get('name', '')} {browser.get('version', '')}".strip()
        return ""


class HarReader:
    """Iterate over `log.entries` without loading the file.

    >>> reader = HarReader(open("file.har", "rb"))
    >>> for entry in reader:            # one dict per request
    ...     ...
    >>> reader.log.pages                # available once iteration has finished
    """

    def __init__(self, source: IO[bytes], limits: Limits = Limits()) -> None:
        self._stream = open_har_stream(source, limits)
        self._limits = limits
        self.log = HarLog()

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return self._entries()

    def _entries(self) -> Iterator[dict[str, Any]]:
        events = ijson.parse(self._stream, use_float=True)
        saw_root = saw_log = saw_entries = False
        builder: _Builder | None = None
        log_key: str | None = None
        try:
            for prefix, event, value in events:
                if builder is not None:
                    builder.feed(event, value)
                    if builder.done:
                        if builder.kind == "entry":
                            self.log.entry_count += 1
                            yield builder.value
                        elif log_key is not None:
                            self.log.fields[log_key] = builder.value
                        builder = None
                    continue
                if prefix == "" and event == "start_map":
                    saw_root = True
                elif prefix == "" and not saw_root:
                    raise HarFormatError("not a valid HAR file: the top level is not an object")
                elif prefix == "log" and event == "start_map":
                    saw_log = True
                elif prefix == "log" and event == "map_key":
                    log_key = value
                elif prefix == "log.entries" and event == "start_array":
                    saw_entries = True
                elif prefix == "log.entries.item":
                    max_entries = self._limits.max_entries
                    if max_entries is not None and self.log.entry_count >= max_entries:
                        raise InputTooLarge(f"the file has more than {max_entries:,} requests")
                    builder = _Builder("entry")
                    builder.feed(event, value)
                    if builder.done:  # a scalar where an entry object should be
                        builder = None
                elif (
                    log_key is not None
                    and log_key != "entries"
                    and prefix == f"log.{log_key}"
                    and event not in ("end_map", "end_array")
                ):
                    builder = _Builder("field")
                    builder.feed(event, value)
                    if builder.done:
                        self.log.fields[log_key] = builder.value
                        builder = None
        except ijson.IncompleteJSONError as exc:
            if self.log.entry_count == 0:
                raise HarFormatError(_describe_json_error(exc, saw_root)) from exc
            self.log.truncated = True  # keep what was read: a cut-off file is still evidence
            return
        except ijson.JSONError as exc:
            if self.log.entry_count == 0:
                raise HarFormatError(_describe_json_error(exc, saw_root)) from exc
            self.log.truncated = True
            return
        if not saw_root:
            raise HarFormatError("not a valid HAR file: the file is empty")
        if not saw_log:
            raise HarFormatError("not a valid HAR file: missing log")
        if not saw_entries:
            raise HarFormatError("not a valid HAR file: missing log.entries")


def _describe_json_error(exc: Exception, saw_root: bool) -> str:
    if not saw_root:
        if "premature" in str(exc).lower():
            return "not a valid HAR file: the file is empty"
        return "not a valid HAR file: it is not JSON"
    if isinstance(exc, ijson.IncompleteJSONError) and "premature" in str(exc).lower():
        return "not a valid HAR file: the file ends before the first request (truncated?)"
    return "not a valid HAR file: the JSON is malformed before the first request"


class _Builder:
    """Builds one JSON value from ijson events (a tiny ijson.ObjectBuilder)."""

    __slots__ = ("_stack", "done", "kind", "value")

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self._stack: list[Any] = []
        self.value: Any = None
        self.done = False

    def feed(self, event: str, value: Any) -> None:
        stack = self._stack
        if event == "map_key":
            stack.append(value)
            return
        if event == "start_map":
            container: Any = {}
        elif event == "start_array":
            container = []
        elif event in ("end_map", "end_array"):
            finished = stack.pop()
            self._attach(finished)
            return
        else:
            self._attach(value)
            return
        stack.append(container)

    def _attach(self, item: Any) -> None:
        stack = self._stack
        if not stack:
            self.value = item
            self.done = True
            return
        top = stack[-1]
        if isinstance(top, list):
            top.append(item)
        elif isinstance(top, str):  # a pending key
            key = stack.pop()
            stack[-1][key] = item
        else:  # pragma: no cover - ijson never emits a value directly into a map
            raise HarFormatError("not a valid HAR file: malformed object")
