"""One pass over a HAR file: read → extract metadata → redact → write → run rules.

The CLI, the web upload and the helpdesk worker all call `process`. It reads the
input once, keeps one entry in memory at a time, and never writes the unredacted
input anywhere. With ``trusted_redacted=True`` it re-analyses a file this tool
already redacted (for example after the rules change), using the metadata stored
on each entry instead of redacting again.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import IO, Any

from hartriage import ENGINE_VERSION
from hartriage.har import metadata
from hartriage.har.metadata import EntryMeta
from hartriage.har.model import PHASES, Entry
from hartriage.har.redactor import DEFAULT_POLICY, RedactionPolicy, RedactionReport, Redactor
from hartriage.har.stream_reader import HarLog, HarReader, Limits
from hartriage.har.writer import HarWriter
from hartriage.rules import Finding, RuleConfig, RuleEngine


@dataclass(frozen=True, slots=True)
class EntryRow:
    """The waterfall's view of a request: small, no headers, no bodies."""

    number: int
    started_ms: float | None  # milliseconds after the first request started
    method: str
    url: str
    host: str
    status: int
    error: str
    mime: str
    resource_type: str
    time_ms: float
    timings: dict[str, float | None]
    request_bytes: int
    response_bytes: int
    failed: bool
    offset: int | None = None
    length: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "started_ms": self.started_ms,
            "method": self.method,
            "url": self.url,
            "host": self.host,
            "status": self.status,
            "error": self.error,
            "mime": self.mime,
            "resource_type": self.resource_type,
            "time_ms": self.time_ms,
            "timings": self.timings,
            "request_bytes": self.request_bytes,
            "response_bytes": self.response_bytes,
            "failed": self.failed,
        }


@dataclass
class Stats:
    entries: int = 0
    failed: int = 0
    hosts: Counter[str] = field(default_factory=Counter)
    statuses: Counter[str] = field(default_factory=Counter)
    first_started: datetime | None = None
    last_finished: datetime | None = None
    bytes_received: int = 0

    def observe(self, entry: Entry) -> None:
        self.entries += 1
        if entry.failed:
            self.failed += 1
        if entry.host:
            self.hosts[entry.host] += 1
        self.statuses[f"{entry.status // 100}xx" if entry.status else "no response"] += 1
        self.bytes_received += entry.transfer_size or entry.response_body_size
        if entry.started:
            if self.first_started is None or entry.started < self.first_started:
                self.first_started = entry.started
            end = entry.started + timedelta(milliseconds=entry.time_ms)
            if self.last_finished is None or end > self.last_finished:
                self.last_finished = end

    def to_dict(self) -> dict[str, Any]:
        duration = (
            (self.last_finished - self.first_started).total_seconds()
            if self.first_started and self.last_finished
            else None
        )
        return {
            "entries": self.entries,
            "failed": self.failed,
            "hosts": dict(self.hosts.most_common(20)),
            "host_count": len(self.hosts),
            "statuses": dict(self.statuses),
            "first_started": self.first_started.isoformat() if self.first_started else None,
            "last_finished": self.last_finished.isoformat() if self.last_finished else None,
            "duration_seconds": round(duration, 3) if duration is not None else None,
            "bytes_received": self.bytes_received,
        }


@dataclass
class ProcessResult:
    findings: list[Finding]
    report: RedactionReport
    log: HarLog
    stats: Stats
    rows: list[EntryRow]
    engine_version: str = ENGINE_VERSION
    offsets: list[tuple[int, int]] = field(default_factory=list)
    redacted_log_fields: dict[str, Any] = field(default_factory=dict)

    @property
    def truncated(self) -> bool:
        # A stored redacted file is complete JSON even when the original was cut off;
        # it carries the original's flag in log._hartriage.
        stored = self.redacted_log_fields.get("_hartriage") or {}
        return self.log.truncated or bool(stored.get("truncated"))


def process(
    source: IO[bytes],
    *,
    out: IO[bytes] | None = None,
    policy: RedactionPolicy = DEFAULT_POLICY,
    config: RuleConfig | None = None,
    rules: Iterable[str] | None = None,
    limits: Limits = Limits(),
    trusted_redacted: bool = False,
    keep_rows: bool = True,
    on_row: Callable[[EntryRow], None] | None = None,
    analyse: bool = True,
) -> ProcessResult:
    reader = HarReader(source, limits)
    redactor = Redactor(policy)
    writer = HarWriter(out) if out is not None else None
    engine = RuleEngine(config, only=rules)
    stats = Stats()
    rows: list[EntryRow] = []
    first_start: datetime | None = None

    for number, raw in enumerate(reader, start=1):
        if not isinstance(raw, dict):
            continue
        if trusted_redacted:
            meta = EntryMeta.from_dict(raw.get("_hartriage"))
        else:
            meta = metadata.extract(raw, redactor)
            redactor.redact_entry(raw)
            raw["_hartriage"] = meta.to_dict()
        offset = length = None
        if writer is not None:
            offset, length = writer.entry(raw)
        entry = Entry.from_har(number, raw, meta)
        del raw
        if analyse:
            engine.observe(entry)
        stats.observe(entry)
        if keep_rows or on_row is not None:
            if first_start is None and entry.started:
                first_start = entry.started
            row = EntryRow(
                number=entry.number,
                started_ms=(entry.started - first_start).total_seconds() * 1000
                if entry.started and first_start
                else None,
                method=entry.method,
                url=entry.url[:2000],
                host=entry.host,
                status=entry.status,
                error=entry.error[:200],
                mime=entry.mime[:100],
                resource_type=entry.resource_type[:40],
                time_ms=round(entry.time_ms, 3),
                timings={
                    p: (round(v, 3) if v is not None else None)
                    for p, v in entry.timings.as_dict().items()
                    if p in PHASES
                },
                request_bytes=entry.request_body_size,
                response_bytes=entry.response_body_size,
                failed=entry.failed,
                offset=offset,
                length=length,
            )
            if keep_rows:
                rows.append(row)
            if on_row is not None:
                on_row(row)

    stored = reader.log.fields.get("_hartriage")
    stored = stored if isinstance(stored, dict) else {}
    if trusted_redacted:
        log_fields = dict(reader.log.fields)
        redaction = stored.get("redaction") or {}
    else:
        log_fields = redactor.redact_log_fields(reader.log.fields)
        redaction = redactor.report.to_dict()
    log_fields["_hartriage"] = {
        "engine_version": ENGINE_VERSION,
        "redaction": redaction,
        "truncated": reader.log.truncated or bool(stored.get("truncated")),
    }
    if writer is not None:
        if not trusted_redacted:
            log_fields["creator"] = log_fields.get("creator") or {"name": "unknown", "version": ""}
        writer.close(log_fields)
    # Rows sorted by start time make a sensible waterfall even when the file was not.
    if keep_rows and first_start is not None:
        rows.sort(key=lambda r: (r.started_ms if r.started_ms is not None else 0.0, r.number))
    result = ProcessResult(
        findings=engine.finish() if analyse else [],
        report=redactor.report,
        log=reader.log,
        stats=stats,
        rows=rows,
        offsets=writer.offsets if writer is not None else [],
        redacted_log_fields=log_fields,
    )
    return result
