"""Findings → a summary an agent can paste into a ticket.

The summary always has the same six parts, in the order a support engineer reads
a case: what the customer was doing, the first failure, the likely cause, the
evidence, the next step and the KB article. It renders to Markdown, plain text,
JSON and HTML (for helpdesk notes). Everything in it comes from redacted data.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from hartriage import ENGINE_VERSION
from hartriage.rules.base import Finding, kb_slug

DEFAULT_KB_URL = "https://github.com/priyadharshanexe/hartriage/blob/main/kb/{slug}.md"


@dataclass
class Summary:
    activity: list[str]
    first_failure: str
    likely_cause: str
    evidence: list[str]
    next_step: str
    kb_title: str
    kb_url: str
    redaction: str
    other_findings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    lead_rule: str = ""
    engine_version: str = ENGINE_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _lead(findings: list[Finding]) -> Finding | None:
    if not findings:
        return None
    first = next((f for f in findings if f.rule_id == "R001"), None)
    first_entry = first.entry if first else None
    candidates = [f for f in findings if f.rule_id != "R001" and f.severity.value != "info"]
    if first_entry is not None:
        # A specific explanation of the first failure beats the generic one.
        related = [f for f in candidates if first_entry in f.entries]
        if related:
            return min(related, key=lambda f: (f.severity.rank, f.entry or 0))
        return first
    if candidates:
        return candidates[0]
    return findings[0]


def evidence_lines(finding: Finding) -> list[str]:
    ev = finding.evidence
    lines = []
    nums = finding.entries[:10]
    if nums:
        more = f" (+{len(finding.entries) - 10} more)" if len(finding.entries) > 10 else ""
        lines.append("Requests " + ", ".join(f"#{n}" for n in nums) + more)
    if isinstance(ev.get("status"), int) and ev["status"]:
        lines.append(f"Status {ev['status']}")
    if ev.get("www_authenticate"):
        lines.append(f"WWW-Authenticate: {ev['www_authenticate']}")
    if ev.get("credentials") is not None and finding.rule_id == "R002":
        creds = ev.get("credentials") or []
        lines.append("Credentials sent: " + (", ".join(creds) if creds else "none"))
    jwt = ev.get("jwt")
    if isinstance(jwt, dict) and jwt.get("exp"):
        lines.append(
            f"Token {jwt.get('token', '')} exp {jwt['exp']}"
            + (f", iat {jwt['iat']}" if jwt.get("iat") else "")
        )
    if ev.get("errors"):
        lines.append("Browser error: " + ", ".join(ev["errors"][:3]))
    if ev.get("error") and isinstance(ev["error"], str) and finding.rule_id == "R001":
        lines.append(f"Browser error: {ev['error']}")
    if ev.get("retry_after_seconds") is not None:
        lines.append(f"Retry-After: {ev['retry_after_seconds']:.0f} s")
    if ev.get("early_retries"):
        lines.append("Retried too early: " + ", ".join(f"#{n}" for n in ev["early_retries"][:10]))
    if ev.get("limits"):
        lines.append("Limits: " + ", ".join(f"{k}: {v}" for k, v in list(ev["limits"].items())[:4]))
    for req in (ev.get("requests") or [])[:5]:
        lines.append(
            f"#{req['entry']} took {req['total_ms'] / 1000:.1f} s"
            f" ({ev.get('phase')}: {req['phase_ms'] / 1000:.1f} s) {req['url']}"
        )
    if ev.get("reason"):
        lines.append(f"CORS: {ev['reason']}")
    for chain_hop in (ev.get("chain") or [])[:6]:
        lines.append(f"#{chain_hop['entry']} {chain_hop['status']} {chain_hop['url']}")
    if ev.get("message") and finding.rule_id == "R009":
        lines.append(f"Error {ev.get('code') or ''}: {ev['message']}".strip())
    for ids in (ev.get("correlation_ids") or [])[:5]:
        pairs = [f"{k}={v}" for k, v in ids.items() if k != "entry"]
        if pairs:
            lines.append(f"#{ids.get('entry')} " + " ".join(pairs))
    if ev.get("request_bytes"):
        lines.append(f"Request body: {ev['request_bytes']:,} bytes")
    if ev.get("cookie_header_bytes"):
        lines.append(f"Cookie header: {ev['cookie_header_bytes']:,} bytes")
    return lines


def build_summary(
    findings: list[Finding],
    stats: dict[str, Any],
    redaction_sentence: str,
    *,
    pages: list[str] | None = None,
    browser: str = "",
    truncated: bool = False,
    kb_url_template: str = DEFAULT_KB_URL,
    entry_meta: dict[int, dict[str, str]] | None = None,
) -> Summary:
    hosts = list((stats.get("hosts") or {}).items())[:4]
    activity = []
    if pages:
        activity.append(
            "Pages: "
            + "; ".join(p[:120] for p in pages[:3])
            + (f" (+{len(pages) - 3} more)" if len(pages) > 3 else "")
        )
    if hosts:
        activity.append("Main hosts: " + ", ".join(f"{h} ({n})" for h, n in hosts))
    span = stats.get("duration_seconds")
    when = stats.get("first_started")
    activity.append(
        f"{stats.get('entries', 0)} request{'' if stats.get('entries') == 1 else 's'}"
        + (
            (f" over {span:.0f} s" if span >= 1 else " within 1 s")
            if isinstance(span, int | float) and stats.get("entries")
            else ""
        )
        + (f", starting {when[:19].replace('T', ' ')} UTC" if when else "")
        + (f", recorded in {browser}" if browser else "")
    )

    first = next((f for f in findings if f.rule_id == "R001"), None)
    if first:
        ev = first.evidence
        outcome = (
            f"{ev.get('status')} {ev.get('status_text') or ''}".strip()
            if ev.get("status")
            else ev.get("error") or "no response"
        )
        first_failure = f"Request #{first.entry}: {ev.get('method')} {ev.get('url')} → {outcome}"
    elif not stats.get("entries"):
        first_failure = "None: the recording contains no requests."
    elif stats.get("failed"):
        # R001 was left out (for example `--rules R005`): don't claim nothing failed.
        first_failure = (
            f"Not checked: {stats['failed']} request(s) failed, but rule R001 was not run."
        )
    else:
        first_failure = "None: every request in the file succeeded."

    lead = _lead(findings)
    if lead is None and not stats.get("entries"):
        likely = (
            "The HAR file is empty: recording was started after the problem happened, or the"
            " export was saved before the page made any requests."
        )
        step = (
            "Ask the customer to open DevTools first, turn on 'Preserve log', reproduce the"
            " problem, and only then export the HAR file."
        )
        evidence: list[str] = ["0 requests in the file"]
        kb_title, kb_url = (
            "How to record a useful HAR file",
            kb_url_template.format(slug="recording-a-har"),
        )
    elif lead is None:
        likely = (
            "No failed or unusually slow requests were recorded. The problem may not have"
            " been reproduced while recording, or it happens in the page's own code."
        )
        step = (
            "Ask the customer to start recording before reproducing the problem, keep"
            " 'Preserve log' on, and send the browser console output as well."
        )
        evidence = [f"{stats.get('entries', 0)} requests, none failed"]
        kb_title, kb_url = (
            "How to record a useful HAR file",
            kb_url_template.format(slug="recording-a-har"),
        )
    else:
        likely = lead.cause + (" (likely)" if lead.confidence == "likely" else "")
        step = lead.next_step
        evidence = evidence_lines(lead)
        slug = kb_slug(lead.rule_id, lead.rule_slug)
        kb_title, kb_url = (
            f"{lead.rule_id}: {lead.title.split(':')[0]}",
            kb_url_template.format(slug=slug),
        )

    others = [f"[{f.severity.value}] {f.title}" for f in findings if f is not lead][:8]
    notes = []
    if truncated:
        notes.append(
            "The HAR file was cut off; only the complete requests before the cut were analysed."
        )
    return Summary(
        activity=activity,
        first_failure=first_failure,
        likely_cause=likely,
        evidence=list(dict.fromkeys(evidence))[:10],
        next_step=step,
        kb_title=kb_title,
        kb_url=kb_url,
        redaction=redaction_sentence,
        other_findings=others,
        notes=notes,
        lead_rule=lead.rule_id if lead else "",
    )


# --------------------------------------------------------------------- renderers


def to_markdown(s: Summary, title: str = "HAR Triage summary") -> str:
    out = [f"### {title}", ""]
    out += ["**What the customer was doing**", *[f"- {a}" for a in s.activity], ""]
    out += [f"**First failure:** {s.first_failure}", ""]
    out += [f"**Likely cause:** {s.likely_cause}", ""]
    out += ["**Evidence**", *[f"- {_md_code(e)}" for e in s.evidence], ""]
    out += [f"**Suggested next step:** {s.next_step}", ""]
    out += [f"**KB article:** [{s.kb_title}]({s.kb_url})", ""]
    if s.other_findings:
        out += ["**Other findings**", *[f"- {o}" for o in s.other_findings], ""]
    for note in s.notes:
        out += [f"> {note}", ""]
    out += [f"_Redaction: {s.redaction} Engine {s.engine_version}._"]
    return "\n".join(out) + "\n"


def _md_code(line: str) -> str:
    return line.replace("|", "\\|")


def to_text(s: Summary, title: str = "HAR Triage summary") -> str:
    out = [title, "=" * len(title), "", "What the customer was doing:"]
    out += [f"  - {a}" for a in s.activity]
    out += [
        "",
        f"First failure: {s.first_failure}",
        "",
        f"Likely cause: {s.likely_cause}",
        "",
        "Evidence:",
    ]
    out += [f"  - {e}" for e in s.evidence]
    out += ["", f"Suggested next step: {s.next_step}", "", f"KB article: {s.kb_title} - {s.kb_url}"]
    if s.other_findings:
        out += ["", "Other findings:", *[f"  - {o}" for o in s.other_findings]]
    for note in s.notes:
        out += ["", f"Note: {note}"]
    out += ["", f"Redaction: {s.redaction} Engine {s.engine_version}."]
    return "\n".join(out) + "\n"


def to_json(s: Summary, findings: list[Finding], extra: dict[str, Any] | None = None) -> str:
    payload = {"summary": s.to_dict(), "findings": [f.to_dict() for f in findings], **(extra or {})}
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n"


_REQUEST_NUMBER = re.compile(r"#(\d+)")


def to_html(s: Summary, title: str = "HAR Triage summary", marker: str = "") -> str:
    """HTML for helpdesk private notes. Every value is escaped: HAR content is untrusted.

    Found live: Zendesk turns "#3" in a comment into a link to ticket 3, so "Request #3"
    pointed agents at another customer's ticket. "#<span>3</span>" reads the same and is
    not linked.
    """

    def e(value: str) -> str:
        return _REQUEST_NUMBER.sub(r"#<span>\1</span>", html.escape(value))

    def items(values: list[str]) -> str:
        return "<ul>" + "".join(f"<li>{e(v)}</li>" for v in values) + "</ul>"

    parts = [
        f"<h3>{e(title)}</h3>",
        "<p><strong>What the customer was doing</strong></p>",
        items(s.activity),
        f"<p><strong>First failure:</strong> {e(s.first_failure)}</p>",
        f"<p><strong>Likely cause:</strong> {e(s.likely_cause)}</p>",
        "<p><strong>Evidence</strong></p>",
        items(s.evidence),
        f"<p><strong>Suggested next step:</strong> {e(s.next_step)}</p>",
        f'<p><strong>KB article:</strong> <a href="{html.escape(s.kb_url, quote=True)}">'
        f"{e(s.kb_title)}</a></p>",
    ]
    if s.other_findings:
        parts += ["<p><strong>Other findings</strong></p>", items(s.other_findings)]
    parts += [f"<p><em>{e(n)}</em></p>" for n in s.notes]
    parts.append(
        f"<p><small>Redaction: {e(s.redaction)} Engine {e(s.engine_version)}."
        f"{' ' + e(marker) if marker else ''}</small></p>"
    )
    return "\n".join(parts)


def summarise(result: Any, kb_url_template: str = DEFAULT_KB_URL) -> Summary:
    """Build the summary for a `pipeline.ProcessResult`."""
    fields = result.redacted_log_fields
    pages = [str(p.get("title") or "") for p in fields.get("pages") or [] if isinstance(p, dict)]
    browser = ""
    for key in ("browser", "creator"):
        value = fields.get(key)
        if isinstance(value, dict) and value.get("name"):
            browser = f"{value.get('name')} {value.get('version', '')}".strip()
            break
    redaction = (fields.get("_hartriage") or {}).get("redaction") or {}
    return build_summary(
        result.findings,
        result.stats.to_dict(),
        str(redaction.get("sentence") or result.report.sentence()),
        pages=[p for p in pages if p],
        browser=browser,
        truncated=result.truncated,
        kb_url_template=kb_url_template,
    )
