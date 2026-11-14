from __future__ import annotations

import gzip
import io
import json
import zipfile
from typing import Any

import pytest

from hartriage.har.stream_reader import HarFormatError, HarReader, InputTooLarge, Limits
from tests.support.har import as_stream, entry, har


def read(data: bytes, limits: Limits = Limits()) -> tuple[list[dict[str, Any]], HarReader]:
    reader = HarReader(io.BytesIO(data), limits)
    return list(reader), reader


def test_reads_entries_and_log_fields_in_any_order() -> None:
    doc = {
        "log": {
            "entries": [entry(), entry(status=404)],
            "version": "1.2",
            "creator": {"name": "Firefox", "version": "140"},
            "pages": [{"id": "page_1", "title": "Orders"}],
        }
    }
    entries, reader = read(json.dumps(doc).encode())
    assert [e["response"]["status"] for e in entries] == [200, 404]
    assert reader.log.creator == "Firefox 140"
    assert reader.log.pages[0]["title"] == "Orders"
    assert reader.log.entry_count == 2


def test_empty_entries_is_valid() -> None:
    entries, reader = read(b'{"log": {"version": "1.2", "entries": []}}')
    assert entries == [] and reader.log.entry_count == 0


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"", "empty"),
        (b"hello there", "not JSON"),
        (b"[1, 2, 3]", "top level is not an object"),
        (b'{"version": "1.2"}', "missing log"),
        (b'{"log": {"version": "1.2"}}', "missing log.entries"),
        (b'{"log": {"entries": [', "truncated"),
    ],
)
def test_bad_input_gets_a_plain_message(data: bytes, message: str) -> None:
    with pytest.raises(HarFormatError, match=message):
        read(data)


def test_truncated_file_keeps_complete_entries() -> None:
    full = json.dumps(har(entry(status=200), entry(status=500), entry(status=201)))
    cut = full[: full.rfind('"startedDateTime"') + 30]  # cut inside the third entry
    entries, reader = read(cut.encode())
    assert [e["response"]["status"] for e in entries] == [200, 500]
    assert reader.log.truncated


def test_gzip_and_zip_are_unpacked() -> None:
    raw = json.dumps(har(entry())).encode()
    assert len(read(gzip.compress(raw))[0]) == 1
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("session.har", raw)
    assert len(read(buffer.getvalue())[0]) == 1


def test_zip_without_exactly_one_har_is_rejected() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("readme.txt", "hi")
    with pytest.raises(HarFormatError, match="exactly one .har"):
        read(buffer.getvalue())


def test_bom_and_invalid_utf8_are_tolerated() -> None:
    raw = json.dumps(
        har(entry(content={"size": 3, "mimeType": "text/plain", "text": "XYZ"}))
    ).encode()
    raw = b"\xef\xbb\xbf" + raw.replace(b"XYZ", b"X\xffZ")
    entries, _ = read(raw)
    assert entries[0]["response"]["content"]["text"] == "X�Z"


def test_size_limits() -> None:
    raw = json.dumps(har(*[entry() for _ in range(5)])).encode()
    with pytest.raises(InputTooLarge, match="larger than"):
        read(raw, Limits(max_bytes=100))
    with pytest.raises(InputTooLarge, match="more than 3 requests"):
        read(raw, Limits(max_entries=3))


def test_decompressed_size_is_checked_so_a_zip_bomb_cannot_expand() -> None:
    bomb = gzip.compress(b'{"log": {"entries": [], "pad": "' + b"A" * 2_000_000 + b'"}}')
    assert len(bomb) < 10_000
    with pytest.raises(InputTooLarge, match="unpacked file"):
        read(bomb, Limits(max_bytes=1_000_000, max_decompressed_bytes=1_000_000))


def test_stream_helper() -> None:
    assert len(list(HarReader(as_stream(har(entry()))))) == 1
