"""Memory stays flat: a 50 MB HAR is processed with a small, fixed ceiling.

The file is generated on the fly (2,000 requests with 25 KB bodies), written to a
temporary file and streamed through the whole pipeline with the redacted copy
going to a null sink. tracemalloc measures every Python allocation.
"""

from __future__ import annotations

import json
import os
import tracemalloc
from pathlib import Path
from typing import IO

import pytest

from hartriage.pipeline import process
from tests.support.har import entry, headers

CEILING_MB = 16


class Null:
    def write(self, data: bytes) -> int:
        return len(data)

    def flush(self) -> None:
        pass


def write_har(path: Path, entries: int, body_bytes: int) -> int:
    body = "y" * body_bytes
    with path.open("w", encoding="utf-8") as f:
        f.write('{"log": {"version": "1.2", "creator": {"name": "gen", "version": "1"}, "entries": [')
        for i in range(entries):
            e = entry(
                f"https://api.example.com/items/{i}?token=tok{i:08d}abcdefgh",
                status=500 if i % 50 == 0 else 200,
                request_headers=headers(Authorization=f"Bearer tok{i:08d}abcdefgh", Cookie="sid=s1234567"),
                content={"size": body_bytes, "mimeType": "text/html", "text": body},
            )
            f.write(("," if i else "") + json.dumps(e))
        f.write("]}}")
    return path.stat().st_size


def peak_mb(path: Path) -> float:
    tracemalloc.start()
    with path.open("rb") as source:
        sink: IO[bytes] = Null()  # type: ignore[assignment]
        result = process(source, out=sink, keep_rows=False)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result.stats.entries > 0
    return peak / (1024 * 1024)


@pytest.mark.slow
def test_50mb_file_stays_under_the_memory_ceiling(tmp_path: Path) -> None:
    big = tmp_path / "big.har"
    size = write_har(big, entries=2100, body_bytes=25_000)
    assert size > 50 * 1024 * 1024
    peak = peak_mb(big)
    print(f"\n50 MB HAR ({size / 1e6:.0f} MB on disk): peak traced memory {peak:.1f} MB")
    assert peak < CEILING_MB


@pytest.mark.slow
def test_memory_does_not_grow_with_file_size(tmp_path: Path) -> None:
    small, large = tmp_path / "small.har", tmp_path / "large.har"
    write_har(small, entries=200, body_bytes=25_000)
    write_har(large, entries=2000, body_bytes=25_000)
    ratio = peak_mb(large) / peak_mb(small)
    # Ten times the data may not cost ten times the memory; a little growth comes from
    # per-request state such as the rule engine's small summaries.
    assert ratio < 2.5, ratio


def test_generator_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "tiny.har"
    write_har(path, entries=3, body_bytes=10)
    with path.open("rb") as f:
        assert json.load(f)["log"]["entries"][0]["response"]["status"] == 500
    os.remove(path)
