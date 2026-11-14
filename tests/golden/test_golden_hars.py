"""Golden files: each recorded HAR produces exactly the findings in expected.json.

The HAR files were recorded with Playwright against tools/fixtures/fault_server.py
(plus expired.badssl.com) in Chromium and Firefox, whose HAR files differ. Each
finding is compared by rule, severity and its kind (for example "expired_token" or
"dns"), so re-recording changes nothing as long as the browsers behave the same.

After an intended change in what the rules find:

    UPDATE_GOLDEN=1 uv run pytest tests/golden    # then review the diff of expected.json
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hartriage.pipeline import process
from hartriage.rules import Finding

HERE = Path(__file__).parent
HARS = sorted((HERE / "hars").glob("*/*.har"))
EXPECTED = HERE / "expected.json"


def describe(f: Finding) -> str:
    ev = f.evidence
    kind = (
        ev.get("kind")
        or ev.get("category")
        or ev.get("phase")
        or ev.get("code")
        or ev.get("status")
        or ""
    )
    return f"{f.rule_id} {f.severity.value} {kind}".strip()


def analyse(path: Path) -> list[str]:
    with path.open("rb") as f:
        return sorted(describe(x) for x in process(f).findings)


def key(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def test_every_scenario_was_recorded_in_both_browsers() -> None:
    names = {p.stem for p in HARS}
    for browser in ("chromium", "firefox"):
        assert {p.stem for p in HARS if p.parent.name == browser} == names


def test_update_golden() -> None:
    if not os.environ.get("UPDATE_GOLDEN"):
        pytest.skip("set UPDATE_GOLDEN=1 to rewrite expected.json")
    EXPECTED.write_text(
        json.dumps({key(p): analyse(p) for p in HARS}, indent=2) + "\n", encoding="utf-8"
    )


@pytest.mark.parametrize("path", HARS, ids=key)
def test_findings_match_golden(path: Path) -> None:
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    assert analyse(path) == expected[key(path)]


@pytest.mark.parametrize("path", HARS, ids=key)
def test_no_recorded_token_survives(path: Path) -> None:
    """The fault server's tokens all start with the same JWT header."""
    import io

    out = io.BytesIO()
    with path.open("rb") as f:
        process(f, out=out)
    raw = path.read_text(encoding="utf-8")
    redacted = out.getvalue().decode("utf-8")
    if "eyJhbGciOiJIUzI1NiIsICJ0eXAiOiAiSldUIn0" in raw:
        assert "eyJhbGciOiJIUzI1NiIsICJ0eXAiOiAiSldUIn0" not in redacted
    assert "hunter2-not-real" not in redacted
