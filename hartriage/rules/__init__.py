"""The rule registry and the engine that runs every rule over a stream of entries."""

from __future__ import annotations

from collections.abc import Iterable

from hartriage.har.model import Entry
from hartriage.rules.base import Context, Finding, Rule, RuleConfig, Severity
from hartriage.rules.r001_first_failure import FirstFailure
from hartriage.rules.r002_auth import Auth
from hartriage.rules.r003_cors import Cors
from hartriage.rules.r004_redirects import Redirects
from hartriage.rules.r005_network import Network
from hartriage.rules.r006_slow import Slow
from hartriage.rules.r007_rate_limit import RateLimit
from hartriage.rules.r008_payload import Payload
from hartriage.rules.r009_api_errors import ApiErrors
from hartriage.rules.r010_mixed_content import MixedContent
from hartriage.rules.r011_server_errors import ServerErrors

RULE_CLASSES: tuple[type[Rule], ...] = (
    FirstFailure,
    Auth,
    Cors,
    Redirects,
    Network,
    Slow,
    RateLimit,
    Payload,
    ApiErrors,
    MixedContent,
    ServerErrors,
)
RULES_BY_ID = {cls.id: cls for cls in RULE_CLASSES}

__all__ = [
    "RULES_BY_ID",
    "RULE_CLASSES",
    "Context",
    "Finding",
    "Rule",
    "RuleConfig",
    "RuleEngine",
    "Severity",
]


class RuleEngine:
    """Feeds each entry to every rule, then collects and orders the findings."""

    def __init__(self, config: RuleConfig | None = None, only: Iterable[str] | None = None):
        wanted = {r.upper() for r in only} if only else None
        unknown = (wanted or set()) - set(RULES_BY_ID)
        if unknown:
            raise ValueError(f"unknown rule id(s): {', '.join(sorted(unknown))}")
        self.rules = [cls() for cls in RULE_CLASSES if wanted is None or cls.id in wanted]
        self.ctx = Context(config=config or RuleConfig())
        self._findings: list[Finding] = []

    def observe(self, entry: Entry) -> None:
        ctx = self.ctx
        ctx.entries_seen += 1
        if entry.started and (ctx.first_started is None or entry.started < ctx.first_started):
            ctx.first_started = entry.started
        if not ctx.page_url and (entry.resource_type == "document" or "text/html" in entry.mime):
            ctx.page_url = entry.url
        for rule in self.rules:
            self._findings.extend(rule.check(entry, ctx))

    def finish(self) -> list[Finding]:
        for rule in self.rules:
            self._findings.extend(rule.finish(self.ctx))
        return sorted(
            self._findings,
            key=lambda f: (f.severity.rank, f.rule_id != "R001", f.entry or 0, f.rule_id),
        )
