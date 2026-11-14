from __future__ import annotations

import io
import json
from typing import Any

from typer.testing import CliRunner

from hartriage.cli.main import app
from hartriage.pipeline import process
from hartriage.summary import summarise, to_html, to_json, to_markdown, to_text
from tests.support.har import as_stream, entry, har, headers, make_jwt

SECRET = "abc" + "DEF" + "123456789xyz"


def sample() -> dict[str, Any]:
    return har(
        entry(
            "https://app.example.com/",
            resource_type="document",
            content={"size": 9, "mimeType": "text/html", "text": "<html></html>"},
        ),
        entry(
            "https://api.example.com/v1/me",
            status=401,
            started="2026-11-14T10:00:01.000Z",
            request_headers=headers(Authorization="Bearer " + make_jwt(exp=1_000)),
            response_headers=headers(X_Request_Id="req-1"),
        ),
        entry("https://api.example.com/v1/orders", status=401, started="2026-11-14T10:00:02.000Z"),
        pages=[{"id": "page_1", "title": "Orders – Example"}],
    )


def test_writer_offsets_point_at_each_entry() -> None:
    out = io.BytesIO()
    result = process(as_stream(sample()), out=out)
    data = out.getvalue()
    whole = json.loads(data)
    assert (
        len(whole["log"]["entries"]) == 3
        and whole["log"]["pages"][0]["title"] == "Orders – Example"
    )
    for (start, length), stored in zip(result.offsets, whole["log"]["entries"], strict=True):
        assert json.loads(data[start : start + length]) == stored


def test_reanalysing_the_redacted_file_gives_the_same_findings() -> None:
    out = io.BytesIO()
    first = process(as_stream(sample()), out=out)
    again = process(io.BytesIO(out.getvalue()), trusted_redacted=True)
    assert [f.to_dict() for f in again.findings] == [f.to_dict() for f in first.findings]
    assert again.redacted_log_fields["_hartriage"]["redaction"]["total_secrets"] == 1


def test_summary_sections_and_renderers() -> None:
    result = process(as_stream(sample()))
    summary = summarise(result)
    assert summary.first_failure.startswith("Request #2: GET https://api.example.com/v1/me → 401")
    assert "expired" in summary.likely_cause
    assert summary.kb_url.endswith("/kb/R002-auth.md")
    md = to_markdown(summary)
    for heading in (
        "What the customer was doing",
        "First failure",
        "Likely cause",
        "Evidence",
        "Suggested next step",
        "KB article",
    ):
        assert heading in md
    assert "Likely cause" in to_text(summary)
    assert json.loads(to_json(summary, result.findings))["summary"]["lead_rule"] == "R002"


def test_html_escapes_har_content() -> None:
    evil = har(entry("https://x.com/<script>alert(1)</script>", status=500))
    html = to_html(summarise(process(as_stream(evil))))
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_clean_file_summary() -> None:
    summary = summarise(process(as_stream(har(entry(), entry()))))
    assert summary.first_failure.startswith("None") and "recording" in summary.kb_url


def test_cli_analyze_and_redact(tmp_path) -> None:  # type: ignore[no-untyped-def]
    source = tmp_path / "in.har"
    source.write_text(json.dumps(har(entry(f"https://a.com/?token={SECRET}", status=500))))
    runner = CliRunner()
    clean = tmp_path / "clean.har"
    result = runner.invoke(
        app, ["analyze", str(source), "--redacted-out", str(clean), "-f", "json"]
    )
    assert result.exit_code == 0, result.output
    assert SECRET not in clean.read_text() and SECRET not in result.stdout
    assert json.loads(result.stdout)["findings"][0]["rule_id"] == "R001"
    assert runner.invoke(app, ["analyze", str(source), "--fail-on", "high"]).exit_code == 1
    out2 = tmp_path / "out2.har"
    redact = runner.invoke(app, ["redact", str(source), "-o", str(out2)])
    assert redact.exit_code == 0 and "Removed 1 token" in redact.stdout
    bad = tmp_path / "bad.har"
    bad.write_text("not json")
    failed = runner.invoke(app, ["analyze", str(bad)])
    assert failed.exit_code == 2 and "not JSON" in failed.output
    assert "R011" in runner.invoke(app, ["rules"]).stdout
