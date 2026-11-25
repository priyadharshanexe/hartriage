"""Benchmark a running stack (docker compose up --build): one HAR at the size limit,
and N uploads at once. Prints a Markdown table; memory comes from `docker stats`.

    uv run python -m tools.bench [--concurrent 10 25] [--size-mb 98]
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

API = "http://127.0.0.1:8200"
SAMPLE = (
    Path(__file__).resolve().parents[1] / "tools" / "fixtures" / "samples" / "checkout-broken.har"
)


def write_har(path: Path, target_bytes: int) -> tuple[int, int]:
    """A HAR of about `target_bytes`, every request carrying a token and a cookie."""
    body = "y" * 4800
    entries = 0
    with path.open("w", encoding="utf-8") as f:
        f.write(
            '{"log": {"version": "1.2", "creator": {"name": "bench", "version": "1"}, "entries": ['
        )
        while f.tell() < target_bytes - 8000:
            e = {
                "startedDateTime": "2026-11-25T10:00:00.000Z",
                "time": 120,
                "request": {
                    "method": "GET",
                    "url": f"https://api.example.test/items/{entries}?token=tok{entries:08d}abcdefgh",
                    "httpVersion": "HTTP/1.1",
                    "headers": [
                        {"name": "Authorization", "value": f"Bearer tok{entries:08d}abcdefgh"},
                        {"name": "Cookie", "value": "sid=s1234567"},
                    ],
                    "queryString": [],
                    "cookies": [],
                    "headersSize": -1,
                    "bodySize": 0,
                },
                "response": {
                    "status": 500 if entries % 50 == 0 else 200,
                    "statusText": "",
                    "httpVersion": "HTTP/1.1",
                    "headers": [],
                    "cookies": [],
                    "content": {"size": len(body), "mimeType": "text/html", "text": body},
                    "redirectURL": "",
                    "headersSize": -1,
                    "bodySize": len(body),
                },
                "cache": {},
                "timings": {"send": 1, "wait": 100, "receive": 19},
            }
            f.write(("," if entries else "") + json.dumps(e))
            entries += 1
        f.write("]}}")
    return path.stat().st_size, entries


class MemoryPeak:
    """Sample `docker stats` for some services until stopped; keep each one's peak."""

    def __init__(self, services: list[str]) -> None:
        self.services = services
        self.peak: dict[str, float] = dict.fromkeys(services, 0.0)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> MemoryPeak:
        self._thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self._stop.set()
        self._thread.join()

    def _run(self) -> None:
        names = [f"hartriage-{s}-1" for s in self.services]
        while not self._stop.is_set():
            out = subprocess.run(  # noqa: S603 - fixed argv, our own container names
                ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}", *names],  # noqa: S607
                capture_output=True,
                text=True,
                check=False,
            ).stdout
            for line in out.splitlines():
                name, usage = line.split(" ", 1)
                value = usage.split("/")[0].strip()
                mb = (
                    float(value[:-3]) * (1024 if value.endswith("GiB") else 1)
                    if value[-3:] in ("MiB", "GiB")
                    else 0.0
                )
                service = name.removeprefix("hartriage-").removesuffix("-1")
                self.peak[service] = max(self.peak[service], mb)


def account(c: httpx.Client) -> str:
    stamp = time.time_ns()
    r = c.post(
        "/v1/auth/register",
        json={
            "name": "Bench",
            "email": f"bench-{stamp}@example.com",
            "password": "bench password 1",
            "organization": f"Bench {stamp}",
        },
    )
    r.raise_for_status()
    return str(r.json()["access_token"])


def wait_done(c: httpx.Client, token: str, ids: list[str], timeout: float = 900) -> float:
    start = time.perf_counter()
    pending = set(ids)
    while pending and time.perf_counter() - start < timeout:
        for i in list(pending):
            status = c.get(
                f"/v1/analyses/{i}", headers={"Authorization": f"Bearer {token}"}
            ).json()["status"]
            if status in ("done", "failed"):
                if status == "failed":
                    raise RuntimeError(f"analysis {i} failed")
                pending.discard(i)
        time.sleep(0.25)
    if pending:
        raise TimeoutError(f"{len(pending)} analyses not done")
    return time.perf_counter() - start


def upload(token: str, data: bytes, name: str) -> tuple[str, float]:
    start = time.perf_counter()
    with httpx.Client(base_url=API, timeout=600) as c:
        r = c.post(
            f"/v1/uploads?filename={name}",
            content=data,
            headers={"Authorization": f"Bearer {token}"},
        )
    r.raise_for_status()
    return str(r.json()["analysis_id"]), time.perf_counter() - start


def large(size_mb: int) -> None:
    with tempfile.TemporaryDirectory() as d, httpx.Client(base_url=API, timeout=600) as c:
        path = Path(d) / "large.har"
        size, entries = write_har(path, size_mb * 1024 * 1024)
        data = path.read_bytes()
        token = account(c)
        with MemoryPeak(["api", "worker"]) as mem:
            analysis_id, upload_s = upload(token, data, "large.har")
            analyse_s = wait_done(c, token, [analysis_id])
        print(
            f"| One file at the limit | {size / 1024 / 1024:.0f} MB, {entries:,} requests | upload + redaction {upload_s:.1f} s; analysis {analyse_s:.1f} s | API peak {mem.peak['api']:.0f} MB, worker peak {mem.peak['worker']:.0f} MB |"
        )


def concurrent(n: int) -> None:
    data = SAMPLE.read_bytes()
    with httpx.Client(base_url=API, timeout=600) as c:
        token = account(c)
        with MemoryPeak(["api", "worker"]) as mem:
            start = time.perf_counter()
            with ThreadPoolExecutor(n) as pool:
                results = list(pool.map(lambda i: upload(token, data, f"c{i}.har"), range(n)))
            accepted = time.perf_counter() - start
            done = wait_done(c, token, [r[0] for r in results]) + accepted
        latencies = sorted(r[1] for r in results)
        p95 = latencies[max(0, round(0.95 * n) - 1)]
        print(
            f"| {n} uploads at once | {len(data) / 1024:.0f} KB each | upload p50 {statistics.median(latencies) * 1000:.0f} ms, p95 {p95 * 1000:.0f} ms; all analysed in {done:.1f} s | API peak {mem.peak['api']:.0f} MB, worker peak {mem.peak['worker']:.0f} MB |"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrent", type=int, nargs="*", default=[10, 25])
    parser.add_argument("--size-mb", type=int, default=98)
    args = parser.parse_args()
    print("| Run | Input | Time | Memory |\n|---|---|---|---|")
    for n in args.concurrent:
        concurrent(n)
    large(args.size_mb)


if __name__ == "__main__":
    main()
