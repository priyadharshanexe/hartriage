"""Intake: stream a raw HAR through redaction straight into object storage.

This is the only code that ever sees an unredacted file, and it only sees it in
memory, one entry at a time. What reaches storage is the redacted file plus a
small index of byte offsets (one pair per request) for range reads.
"""

from __future__ import annotations

import hashlib
import io
import re
import uuid
from array import array
from datetime import UTC, datetime, timedelta
from typing import IO, Any

import structlog
from sqlalchemy.orm import Session

from hartriage.core.config import Settings
from hartriage.core.errors import AppError, TooLarge
from hartriage.db.models import Analysis, Artifact
from hartriage.har.stream_reader import HarFormatError, InputTooLarge, Limits
from hartriage.pipeline import process
from hartriage.storage.s3 import ObjectWriter, Storage, writing

log = structlog.get_logger()


class InvalidHar(AppError):
    status, code = 422, "invalid_har"


class _Counting(io.RawIOBase):
    def __init__(self, raw: IO[bytes]) -> None:
        self._raw = raw
        self.count = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        data = self._raw.read(size)
        self.count += len(data)
        return data

    def readinto(self, buffer: Any) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


class _Hashing(io.RawIOBase):
    def __init__(self, out: ObjectWriter) -> None:
        self._out = out
        self.sha = hashlib.sha256()
        self.size = 0

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:
        self.sha.update(data)
        self.size += len(data)
        self._out.write(data)
        return len(data)


def artifact_key(org_id: uuid.UUID, artifact_id: uuid.UUID) -> str:
    return f"orgs/{org_id}/artifacts/{artifact_id}/redacted.har"


def index_key(storage_key: str) -> str:
    return storage_key.rsplit("/", 1)[0] + "/index.bin"


def clean_filename(name: str | None) -> str:
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[^\w.\- ()]+", "_", base).strip()[:200]
    return base or "upload.har"


def intake(
    db: Session,
    storage: Storage,
    settings: Settings,
    source: IO[bytes],
    *,
    org_id: uuid.UUID,
    source_kind: str,
    filename: str | None,
    created_by: uuid.UUID | None = None,
    case_id: uuid.UUID | None = None,
    external_attachment_id: str | None = None,
) -> Analysis:
    artifact_id = uuid.uuid4()
    key = artifact_key(org_id, artifact_id)
    counted = _Counting(source)
    limits = Limits(
        max_bytes=settings.max_upload_bytes,
        max_decompressed_bytes=settings.max_decompressed_bytes,
        max_entries=settings.max_entries,
    )
    try:
        with writing(storage, key) as writer:
            hashing = _Hashing(writer)
            result = process(counted, out=hashing, limits=limits, keep_rows=False, analyse=False)  # type: ignore[arg-type]
    except InputTooLarge as exc:
        raise TooLarge(f"The file is too large: {exc}.") from exc
    except HarFormatError as exc:
        message = str(exc)
        raise InvalidHar(message[:1].upper() + message[1:] + ".") from exc

    offsets = array("Q")
    for start, length in result.offsets:
        offsets.extend((start, length))
    with writing(storage, index_key(key)) as writer:
        writer.write(offsets.tobytes())

    now = datetime.now(UTC)
    redaction = result.report.to_dict()
    artifact = Artifact(
        id=artifact_id,
        org_id=org_id,
        case_id=case_id,
        kind="har",
        source=source_kind,
        original_filename=clean_filename(filename),
        external_attachment_id=external_attachment_id,
        size_bytes=hashing.size,
        original_size_bytes=counted.count,
        sha256_of_redacted=hashing.sha.hexdigest(),
        storage_key=key,
        entry_count=result.stats.entries,
        redaction_summary=redaction,
        created_by=created_by,
        expires_at=now + timedelta(days=settings.retention_days),
    )
    analysis = Analysis(
        org_id=org_id, artifact_id=artifact_id, status="queued", created_by=created_by
    )
    db.add(artifact)
    db.flush()
    db.add(analysis)
    db.flush()
    log.info(
        "artifact_stored",
        artifact_id=str(artifact_id),
        entries=result.stats.entries,
        redacted_bytes=hashing.size,
        secrets=redaction["total_secrets"],
    )
    return analysis


def load_offsets(storage: Storage, storage_key: str) -> list[tuple[int, int]]:
    data = storage.reader(index_key(storage_key)).read()
    values = array("Q")
    values.frombytes(data)
    return [(values[i], values[i + 1]) for i in range(0, len(values), 2)]
