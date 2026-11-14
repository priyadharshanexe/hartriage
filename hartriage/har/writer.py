"""Write a redacted HAR file entry by entry, recording where each entry lands.

The output is ordinary HAR 1.2 JSON with one entry per line. Entries come first
(so they can be streamed), then the other `log` fields, which are only known once
the input has been read to the end. JSON key order carries no meaning, so any HAR
viewer (Chrome DevTools included) opens the file.

`offsets` holds (start, length) in bytes for every entry. The web app uses them to
fetch a single request from object storage with a range read instead of
downloading the whole file.
"""

from __future__ import annotations

import json
from typing import IO, Any


class HarWriter:
    def __init__(self, out: IO[bytes]) -> None:
        self._out = out
        self.position = 0
        self.count = 0
        self.offsets: list[tuple[int, int]] = []
        self._write(b'{"log":{"entries":[\n')

    def _write(self, data: bytes) -> None:
        self._out.write(data)
        self.position += len(data)

    def entry(self, entry: dict[str, Any]) -> tuple[int, int]:
        if self.count:
            self._write(b",\n")
        data = json.dumps(entry, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8", "surrogatepass"
        )
        start = self.position
        self._write(data)
        self.count += 1
        self.offsets.append((start, len(data)))
        return start, len(data)

    def close(self, log_fields: dict[str, Any]) -> None:
        fields = {k: v for k, v in log_fields.items() if k != "entries"}
        fields.setdefault("version", "1.2")
        fields.setdefault("creator", {"name": "HAR Triage", "version": "1"})
        tail = json.dumps(fields, ensure_ascii=False, separators=(",", ":"))[1:-1]
        self._write(b"\n]")
        if tail:
            self._write(b"," + tail.encode("utf-8", "surrogatepass"))
        self._write(b"}}\n")
        self._out.flush()
