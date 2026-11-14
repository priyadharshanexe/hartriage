"""Object storage for redacted files: S3 in production, any S3-compatible server
locally (RustFS in docker compose), and an in-memory store for tests.

Only redacted files are ever written here. Writes stream through a multipart
upload, so a 100 MB file never sits in memory. Reads of a single request use an
HTTP range read.
"""

from __future__ import annotations

import io
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, Any, Protocol

import boto3
import structlog
from botocore.config import Config
from botocore.exceptions import ClientError

from hartriage.core.config import Settings

log = structlog.get_logger()
PART_SIZE = 8 * 1024 * 1024  # S3 minimum is 5 MB for all parts but the last


class Storage(Protocol):
    def writer(self, key: str) -> ObjectWriter: ...
    def read_range(self, key: str, start: int, length: int) -> bytes: ...
    def reader(self, key: str) -> IO[bytes]: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def ensure_ready(self, retention_days: int) -> None: ...
    def ping(self) -> bool: ...


class ObjectWriter(io.RawIOBase):
    """A write-only file. `close()` commits the object; `abort()` throws it away."""

    def writable(self) -> bool:
        return True

    def abort(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


# ------------------------------------------------------------------------ memory


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def writer(self, key: str) -> ObjectWriter:
        store = self

        class _Writer(ObjectWriter):
            def __init__(self) -> None:
                self.buffer = io.BytesIO()
                self.aborted = False

            def write(self, data: Any) -> int:
                return self.buffer.write(data)

            def abort(self) -> None:
                self.aborted = True
                super().close()

            def close(self) -> None:
                if not self.closed and not self.aborted:
                    with store._lock:
                        store.objects[key] = self.buffer.getvalue()
                super().close()

        return _Writer()

    def read_range(self, key: str, start: int, length: int) -> bytes:
        return self.objects[key][start : start + length]

    def reader(self, key: str) -> IO[bytes]:
        return io.BytesIO(self.objects[key])

    def delete(self, key: str) -> None:
        with self._lock:
            self.objects.pop(key, None)

    def exists(self, key: str) -> bool:
        return key in self.objects

    def ensure_ready(self, retention_days: int) -> None:
        pass

    def ping(self) -> bool:
        return True


# ---------------------------------------------------------------------------- S3


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self.sse = settings.s3_sse
        self.lifecycle = settings.s3_lifecycle
        # Any: the stubs' per-call Literal types fight the optional SSE kwargs.
        self.client: Any = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            config=Config(
                s3={"addressing_style": "path"},
                retries={"max_attempts": 5, "mode": "standard"},
                signature_version="s3v4",
            ),
        )

    def _sse(self) -> dict[str, str]:
        return {"ServerSideEncryption": self.sse} if self.sse else {}

    def writer(self, key: str) -> ObjectWriter:
        return _MultipartWriter(self, key)

    def read_range(self, key: str, start: int, length: int) -> bytes:
        response = self.client.get_object(
            Bucket=self.bucket, Key=key, Range=f"bytes={start}-{start + length - 1}"
        )
        data: bytes = response["Body"].read()
        return data

    def reader(self, key: str) -> IO[bytes]:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        body: IO[bytes] = response["Body"]
        return body

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError:
            return False
        return True

    def ping(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            return False
        return True

    def ensure_ready(self, retention_days: int) -> None:
        """Create the bucket, and add an expiry rule as a backstop for the retention job."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            self.client.create_bucket(Bucket=self.bucket)
            log.info("bucket_created", bucket=self.bucket)
        if not self.lifecycle:
            return
        try:
            self.client.put_bucket_lifecycle_configuration(
                Bucket=self.bucket,
                LifecycleConfiguration={
                    "Rules": [
                        {
                            "ID": "expire-artifacts",
                            "Filter": {"Prefix": "orgs/"},
                            "Status": "Enabled",
                            # One day later than the app's own retention: the app deletes first,
                            # the bucket rule catches anything the app missed.
                            "Expiration": {"Days": retention_days + 1},
                            "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 1},
                        }
                    ]
                },
            )
        except ClientError as exc:  # some S3-compatible servers lack lifecycle support
            log.warning("bucket_lifecycle_unavailable", error=str(exc))


class _MultipartWriter(ObjectWriter):
    def __init__(self, storage: S3Storage, key: str) -> None:
        self._s = storage
        self._key = key
        self._buffer = bytearray()
        self._upload_id: str | None = None
        self._parts: list[dict[str, Any]] = []
        self._aborted = False

    def write(self, data: Any) -> int:
        self._buffer += data
        if len(self._buffer) >= PART_SIZE:
            self._flush_part()
        return len(data)

    def _flush_part(self) -> None:
        client, bucket = self._s.client, self._s.bucket
        if self._upload_id is None:
            created = client.create_multipart_upload(Bucket=bucket, Key=self._key, **self._s._sse())
            self._upload_id = created["UploadId"]
        number = len(self._parts) + 1
        part = client.upload_part(
            Bucket=bucket,
            Key=self._key,
            UploadId=self._upload_id,
            PartNumber=number,
            Body=bytes(self._buffer),
        )
        self._parts.append({"ETag": part["ETag"], "PartNumber": number})
        self._buffer.clear()

    def abort(self) -> None:
        self._aborted = True
        if self._upload_id is not None:
            self._s.client.abort_multipart_upload(
                Bucket=self._s.bucket, Key=self._key, UploadId=self._upload_id
            )
        self._buffer.clear()
        super().close()

    def close(self) -> None:
        if self.closed or self._aborted:
            super().close()
            return
        client, bucket = self._s.client, self._s.bucket
        try:
            if self._upload_id is None:  # small file: one plain PUT
                client.put_object(
                    Bucket=bucket,
                    Key=self._key,
                    Body=bytes(self._buffer),
                    ContentType="application/json",
                    **self._s._sse(),
                )
            else:
                if self._buffer:
                    self._flush_part()
                client.complete_multipart_upload(
                    Bucket=bucket,
                    Key=self._key,
                    UploadId=self._upload_id,
                    MultipartUpload={"Parts": self._parts},
                )
        except Exception:
            self.abort()
            raise
        super().close()


# ---------------------------------------------------------------------- factory

_memory = MemoryStorage()
_cache: dict[str, Storage] = {}


def get_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "memory":
        return _memory
    key = f"{settings.s3_endpoint_url}|{settings.s3_bucket}"
    if key not in _cache:
        _cache[key] = S3Storage(settings)
    return _cache[key]


@contextmanager
def writing(storage: Storage, key: str) -> Iterator[ObjectWriter]:
    """Write an object; on any error the partial upload is aborted, never left behind."""
    writer = storage.writer(key)
    try:
        yield writer
    except BaseException:
        writer.abort()
        raise
    writer.close()
