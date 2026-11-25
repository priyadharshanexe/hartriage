"""The S3 backend: multipart streaming writes, range reads, aborts and the lifecycle rule.

Runs against moto (an in-process S3) always, and against the docker compose RustFS
server when it is running.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from moto import mock_aws

from hartriage.core.config import Settings
from hartriage.storage.s3 import PART_SIZE, S3Storage, writing


def rustfs_available() -> bool:
    import socket

    try:
        socket.create_connection(("localhost", 9200), timeout=0.5).close()
    except OSError:
        return False
    return True


@pytest.fixture(params=["moto", "rustfs"])
def storage(request: pytest.FixtureRequest) -> Iterator[S3Storage]:
    if request.param == "moto":
        with mock_aws():
            settings = Settings(
                s3_endpoint_url=None,
                s3_access_key="test",
                s3_secret_key="test",
                s3_bucket="unit-test",
                s3_sse="AES256",
            )
            s = S3Storage(settings)
            s.ensure_ready(30)
            yield s
    else:
        if os.environ.get("CI") or not rustfs_available():
            pytest.skip("RustFS is not running (docker compose up -d s3)")
        s = S3Storage(Settings(s3_bucket="hartriage-unit-test"))
        s.ensure_ready(30)
        yield s


def test_multipart_write_and_range_read(storage: S3Storage) -> None:
    data = os.urandom(PART_SIZE * 2 + 12345)  # three parts
    with writing(storage, "orgs/t/big.bin") as w:
        for i in range(0, len(data), 1 << 20):
            w.write(data[i : i + (1 << 20)])
    assert (
        storage.read_range("orgs/t/big.bin", PART_SIZE - 5, 10)
        == data[PART_SIZE - 5 : PART_SIZE + 5]
    )
    assert storage.reader("orgs/t/big.bin").read() == data
    storage.delete("orgs/t/big.bin")
    assert not storage.exists("orgs/t/big.bin")


def test_failed_write_leaves_nothing(storage: S3Storage) -> None:
    with pytest.raises(RuntimeError), writing(storage, "orgs/t/partial.bin") as w:
        w.write(os.urandom(PART_SIZE + 1))  # one part already uploaded
        raise RuntimeError("redaction failed half-way")
    assert not storage.exists("orgs/t/partial.bin")
    uploads = storage.client.list_multipart_uploads(Bucket=storage.bucket).get("Uploads", [])
    assert [u for u in uploads if u["Key"] == "orgs/t/partial.bin"] == []


def test_lifecycle_rule_backs_up_the_retention_job(storage: S3Storage) -> None:
    rules = storage.client.get_bucket_lifecycle_configuration(Bucket=storage.bucket)["Rules"]
    rule = next(r for r in rules if r["ID"] == "expire-artifacts")
    assert rule["Expiration"]["Days"] == 31


def test_lifecycle_rule_aborts_incomplete_multipart_uploads(storage: S3Storage) -> None:
    rules = storage.client.get_bucket_lifecycle_configuration(Bucket=storage.bucket)["Rules"]
    rule = next(r for r in rules if r["ID"] == "expire-artifacts")
    assert rule["AbortIncompleteMultipartUpload"]["DaysAfterInitiation"] == 1


def test_a_failing_abort_does_not_hide_the_original_error(
    storage: S3Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Storage went down mid-upload: the abort fails too. The caller must still see why
    the upload failed, and the parts are left for the lifecycle rule or the reconciler."""

    def unreachable(**_: object) -> None:
        raise ConnectionError("storage unreachable")

    with pytest.raises(RuntimeError, match="half-way"), writing(storage, "orgs/t/p2.bin") as w:
        w.write(os.urandom(PART_SIZE + 1))
        monkeypatch.setattr(storage.client, "abort_multipart_upload", unreachable)
        raise RuntimeError("redaction failed half-way")
    monkeypatch.undo()
    [left] = [u for u in storage.open_uploads("orgs/t/p2") if u.key == "orgs/t/p2.bin"]
    storage.abort_upload(left)  # what the reconciler does for one older than its cutoff
    assert list(storage.open_uploads("orgs/t/p2")) == []


def test_listing_objects_with_their_age(storage: S3Storage) -> None:
    with writing(storage, "orgs/t/listed.bin") as w:
        w.write(b"x")
    [obj] = [o for o in storage.list("orgs/t/listed") if o.key == "orgs/t/listed.bin"]
    assert obj.modified.tzinfo is not None
    storage.delete("orgs/t/listed.bin")
