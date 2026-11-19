"""Read the live trial credentials from .env.live (gitignored). Never print the values."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load() -> dict[str, str]:
    values: dict[str, str] = {}
    path = ROOT / ".env.live"
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values
