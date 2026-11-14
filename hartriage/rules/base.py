"""The rule interface. Each rule is a small, separately tested class with an ID.

Rules see entries one at a time, in file order, *after* redaction: a finding can
never contain a secret because a rule never sees one. `check` may return findings
straight away; rules that group or compare requests keep a little state and
return their findings from `finish`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar

from hartriage.har.model import Entry


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"critical": 0, "high": 1, "medium": 2, "info": 3}[self.value]


@dataclass
class Finding:
    rule_id: str
    severity: Severity
    title: str
    cause: str  # the likely cause, in one sentence
    next_step: str
    entries: list[int] = field(default_factory=list)  # request numbers, most relevant first
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: str = "certain"  # or "likely"
    rule_slug: str = ""

    @property
    def entry(self) -> int | None:
        return self.entries[0] if self.entries else None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["severity"] = self.severity.value
        data["entry"] = self.entry
        data["kb"] = kb_slug(self.rule_id, self.rule_slug)
        return data


def kb_slug(rule_id: str, slug: str) -> str:
    return f"{rule_id}-{slug}" if slug else rule_id


@dataclass(frozen=True)
class RuleConfig:
    slow_ms: float = 3000
    very_slow_ms: float = 10000
    long_redirect_chain: int = 5
    large_request_bytes: int = 5 * 1024 * 1024
    max_listed: int = 10


@dataclass
class Context:
    config: RuleConfig = field(default_factory=RuleConfig)
    first_started: datetime | None = None
    page_url: str = ""  # the first document the customer loaded
    entries_seen: int = 0


class Rule:
    id: ClassVar[str]
    slug: ClassVar[str]
    title: ClassVar[str]
    summary: ClassVar[str]

    def check(self, entry: Entry, ctx: Context) -> Iterable[Finding]:
        return ()

    def finish(self, ctx: Context) -> Iterable[Finding]:
        return ()

    def finding(self, **kwargs: Any) -> Finding:
        return Finding(rule_id=self.id, rule_slug=self.slug, **kwargs)
