import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { RequestDetail } from "../components/RequestDetail";
import { Button, CopyButton, EmptyState, ErrorState, Input, LoadingState, Notice, Redacted, Select, SeverityBadge, Stat, Tag } from "../components/ui";
import { NO_FILTER, Waterfall, type WaterfallFilter, applyFilter, isFiltered } from "../components/Waterfall";
import { api } from "../lib/api";
import { bytes, dateTime, relative } from "../lib/format";
import type { Analysis, EntriesPage, EntryRow, Finding, Summary } from "../lib/types";
import { SourceBadge } from "./HistoryPage";

async function allEntries(id: string): Promise<{ rows: EntryRow[]; hosts: EntriesPage["hosts"] }> {
  const rows: EntryRow[] = [];
  let cursor = 0;
  let hosts: EntriesPage["hosts"] = [];
  for (;;) {
    const page = await api<EntriesPage>(`/v1/analyses/${id}/entries`, { query: { cursor, limit: 2000 } });
    rows.push(...page.items);
    hosts = page.hosts;
    if (page.next_cursor === null) break;
    cursor = page.next_cursor;
  }
  rows.sort((a, b) => (a.started_ms ?? 0) - (b.started_ms ?? 0) || a.number - b.number);
  return { rows, hosts };
}

/** KB links in a summary point at GitHub (for the ticket); in the app, open the article here. */
export function kbPath(url: string): string | null {
  const match = /\/kb\/([\w-]+)\.md$/.exec(url);
  return match ? `/kb/${match[1]}` : null;
}

const LINK = "font-bold text-signal underline-offset-2 hover:underline";

export function AnalysisPage() {
  const { id = "" } = useParams();
  const { canEdit } = useAuth();
  const queryClient = useQueryClient();
  const analysis = useQuery({
    queryKey: ["analysis", id],
    queryFn: () => api<Analysis>(`/v1/analyses/${id}`),
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 1000 : false),
  });
  const done = analysis.data?.status === "done";
  const findings = useQuery({ queryKey: ["findings", id], queryFn: () => api<{ items: Finding[] }>(`/v1/analyses/${id}/findings`), enabled: done });
  const entries = useQuery({ queryKey: ["entries", id], queryFn: () => allEntries(id), enabled: done });

  const [selected, setSelected] = useState<number | null>(null);
  const [filter, setFilter] = useState<WaterfallFilter>(NO_FILTER);
  const [highlight, setHighlight] = useState<Set<number>>(new Set());
  const [rerunning, setRerunning] = useState(false);
  const [awaitingRerun, setAwaitingRerun] = useState(false);
  const [notice, setNotice] = useState<{ text: string; tone: "ok" | "bad" } | null>(null);
  const clearNotice = useCallback(() => setNotice(null), []);
  // The row stays highlighted after the drawer closes, so you can see where you were.
  const [drawer, setDrawer] = useState(false);
  const closeDetail = useCallback(() => setDrawer(false), []);
  const open = useCallback((n: number | null) => {
    setSelected(n);
    setDrawer(n !== null);
  }, []);
  const status = analysis.data?.status;
  useEffect(() => {
    // The re-run is queued on the worker: confirm only once it is really done.
    if (!awaitingRerun || (status !== "done" && status !== "failed")) return;
    setAwaitingRerun(false);
    setNotice(
      status === "done"
        ? { text: "Re-run finished with the current rules. The summary and findings are up to date.", tone: "ok" }
        : { text: "The re-run failed.", tone: "bad" },
    );
    void queryClient.invalidateQueries({ queryKey: ["findings", id] });
    void queryClient.invalidateQueries({ queryKey: ["entries", id] });
  }, [awaitingRerun, status, queryClient, id]);
  const rows = useMemo(() => applyFilter(entries.data?.rows ?? [], filter), [entries.data, filter]);

  if (analysis.isPending) return <LoadingState />;
  if (analysis.isError) {
    return (
      <ErrorState
        error={analysis.error}
        onRetry={() => void analysis.refetch()}
        action={
          <Link to="/analyses" className="inline-flex h-8 items-center rounded-[5px] border border-rule-2 bg-card px-3 text-sm font-bold hover:bg-paper-2">
            Back to history
          </Link>
        }
      />
    );
  }
  const a = analysis.data;

  function showRequests(f: Finding) {
    setFilter({ ...NO_FILTER, numbers: new Set(f.entries) });
    setHighlight(new Set(f.entries));
    open(f.entry);
  }

  function clearFilters() {
    setFilter(NO_FILTER);
    setHighlight(new Set());
  }

  async function rerun() {
    setRerunning(true);
    try {
      await api(`/v1/analyses/${id}/rerun`, { method: "POST" });
      open(null);
      clearFilters();
      setNotice(null);
      await queryClient.invalidateQueries({ queryKey: ["analysis", id] });
      setAwaitingRerun(true);
    } catch (e) {
      setNotice({ text: e instanceof Error ? e.message : "The re-run failed.", tone: "bad" });
    } finally {
      setRerunning(false);
    }
  }

  const findingCount = findings.data?.items.length;
  const filtered = isFiltered(filter);

  return (
    <div>
      <header className="animate-rise flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-sm text-ink-3">
            <SourceBadge analysis={a} />
            <span>
              analysed <span title={dateTime(a.finished_at ?? a.created_at)}>{relative(a.finished_at ?? a.created_at)}</span>
            </span>
          </div>
          <h1 className="mt-2 font-mono text-lg font-medium break-words text-ink [overflow-wrap:anywhere]">{a.filename ?? "Analysis"}</h1>
        </div>
        {done && canEdit && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => void downloadRedacted(id, a.filename)}>
              Download redacted HAR
            </Button>
            <Button size="sm" busy={rerunning || awaitingRerun} onClick={() => void rerun()}>
              {rerunning ? "Re-running…" : "Re-run analysis"}
            </Button>
          </div>
        )}
      </header>
      {notice && (
        <div className="mt-4">
          <Notice tone={notice.tone} onDone={clearNotice}>
            {notice.text}
          </Notice>
        </div>
      )}

      {a.status !== "done" ? (
        <div className="mt-8">
          {a.status === "failed" ? <ErrorState error={new Error(a.error ?? "The analysis failed.")} /> : <LoadingState label={`Analysis ${a.status}…`} />}
        </div>
      ) : (
        <>
          {a.summary && <Answer id={id} analysis={a} summary={a.summary} />}

          <nav
            aria-label="On this page"
            className="sticky top-[57px] z-10 -mx-4 mt-10 flex gap-1 overflow-x-auto border-y border-rule bg-paper/95 px-4 py-2 text-sm backdrop-blur-sm sm:-mx-6 sm:px-6 md:top-0 md:-mx-10 md:px-10"
          >
            {[
              ["#answer", "Answer"],
              ["#details", "Details"],
              ["#findings", `Findings ${findingCount ?? ""}`],
              ["#requests", `Requests ${entries.data?.rows.length ?? ""}`],
            ].map(([href, label]) => (
              <a key={href} href={href} className="rounded-full px-3 py-1 whitespace-nowrap text-ink-3 transition-colors duration-150 hover:bg-paper-2 hover:text-ink">
                {label}
              </a>
            ))}
          </nav>

          {a.summary && <Details summary={a.summary} />}

          <section id="findings" aria-labelledby="findings-heading" className="scroll-mt-28 pt-12">
            <h2 id="findings-heading" className="mb-5 flex items-baseline gap-3 font-display text-2xl font-medium">
              Findings <span className="font-mono text-base text-ink-3">{findingCount ?? "…"}</span>
            </h2>
            {findings.isPending ? (
              <LoadingState />
            ) : findings.isError ? (
              <ErrorState error={findings.error} onRetry={() => void findings.refetch()} />
            ) : findings.data.items.length === 0 ? (
              <EmptyState title="No findings">Every request succeeded and nothing was slow. The problem may not have been recorded.</EmptyState>
            ) : (
              <ol className="space-y-3">
                {findings.data.items.map((f, i) => (
                  <FindingItem key={f.id} finding={f} index={i} onShow={() => showRequests(f)} />
                ))}
              </ol>
            )}
          </section>

          <section id="requests" aria-labelledby="requests-heading" className="scroll-mt-28 space-y-3 pt-12">
            <h2 id="requests-heading" className="flex items-baseline gap-3 font-display text-2xl font-medium">
              Requests
              <span className="font-mono text-base text-ink-3">
                {entries.data ? (filtered ? `${rows.length} of ${entries.data.rows.length}` : entries.data.rows.length) : "…"}
              </span>
            </h2>
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex h-10 cursor-pointer items-center gap-2 rounded-[5px] border border-rule-2 bg-card px-3 text-sm transition-colors hover:border-ink-3">
                <input type="checkbox" className="h-4 w-4 accent-[var(--primary)]" checked={filter.failedOnly} onChange={(e) => setFilter({ ...filter, failedOnly: e.target.checked, numbers: null })} />
                Failed only
              </label>
              <Select className="w-56" aria-label="Host" value={filter.host} onChange={(e) => setFilter({ ...filter, host: e.target.value, numbers: null })}>
                <option value="">All hosts</option>
                {entries.data?.hosts.map((h) => (
                  <option key={h.host} value={h.host}>
                    {h.host} ({h.count})
                  </option>
                ))}
              </Select>
              <Input
                className="w-40"
                aria-label="Slower than (ms)"
                type="number"
                min={0}
                placeholder="Slower than (ms)"
                value={filter.minMs ?? ""}
                onChange={(e) => setFilter({ ...filter, minMs: e.target.value === "" ? null : Number(e.target.value), numbers: null })}
              />
              <Input className="w-56" type="search" aria-label="Search URLs" placeholder="Search URL or status" value={filter.text} onChange={(e) => setFilter({ ...filter, text: e.target.value, numbers: null })} />
              {/* Always rendered, so the filter bar does not shift when it becomes useful. */}
              <Button size="sm" variant="ghost" disabled={!filtered} onClick={clearFilters}>
                Clear filters
              </Button>
            </div>
            {filter.numbers && (
              <p className="animate-slide-down rounded-[6px] bg-medium/15 px-3 py-2 text-sm">
                Showing the {filter.numbers.size} request{filter.numbers.size === 1 ? "" : "s"} of one finding.
              </p>
            )}
            {entries.isPending ? (
              <LoadingState />
            ) : entries.isError ? (
              <ErrorState error={entries.error} onRetry={() => void entries.refetch()} />
            ) : rows.length === 0 ? (
              <EmptyState
                title={filtered ? "No requests match these filters" : "No requests recorded"}
                action={filtered ? <Button size="sm" onClick={clearFilters}>Clear filters</Button> : undefined}
              >
                {filtered ? "Try a different host, a lower time, or other search text." : "The recording is empty."}
              </EmptyState>
            ) : (
              <Waterfall rows={rows} selected={selected} onSelect={open} highlight={highlight} />
            )}
          </section>
          {drawer && selected !== null && <RequestDetail analysisId={id} number={selected} onClose={closeDetail} />}
        </>
      )}
    </div>
  );
}

function download(text: string, name: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

async function downloadRedacted(id: string, filename: string | null) {
  const text = await api<string>(`/v1/analyses/${id}/redacted.har`, { text: true });
  download(text, `${(filename ?? "file.har").replace(/\.[^.]+$/, "")}.redacted.har`);
}

async function exportJson(id: string) {
  download(await api<string>(`/v1/analyses/${id}/export`, { query: { format: "json" }, text: true }), "analysis.json");
}

const LABELS: Record<string, [string, string]> = {
  tokens: ["token", "tokens"],
  cookies: ["cookie", "cookies"],
  api_keys: ["API key", "API keys"],
  passwords: ["password", "passwords"],
  signatures: ["signature", "signatures"],
  aws_keys: ["AWS key", "AWS keys"],
  private_keys: ["private key", "private keys"],
};

/** The hero: the likely cause, highlighted, and what to do about it. */
function Answer({ id, analysis: a, summary }: { id: string; analysis: Analysis; summary: Summary }) {
  const r = a.redaction;
  const secrets = Object.entries(r.secrets ?? {}).filter(([, v]) => v > 0);
  return (
    <section id="answer" aria-labelledby="answer-heading" className="scroll-mt-28 pt-8">
      <h2 id="answer-heading" className="animate-fade text-sm font-bold text-ink-3">
        Likely cause
      </h2>
      <p className="mt-3 max-w-4xl font-display text-[1.75rem] leading-[1.22] font-medium tracking-[-0.01em] text-ink sm:text-[2.25rem]" data-testid="likely-cause">
        <span className="highlighter">
          <Redacted text={summary.likely_cause} />
        </span>
      </p>
      <div className="animate-rise mt-6 flex max-w-3xl gap-3" style={{ animationDelay: "380ms" }}>
        <span aria-hidden="true" className="mt-0.5 font-bold text-signal">
          →
        </span>
        <p className="text-lg leading-snug text-ink">
          <span className="sr-only">Next step: </span>
          {summary.next_step}
        </p>
      </div>
      <div className="animate-rise mt-6 flex flex-wrap gap-2" style={{ animationDelay: "440ms" }}>
        <CopyButton variant="primary" label="Copy for ticket" getText={() => api<string>(`/v1/analyses/${id}/export`, { query: { format: "md" }, text: true })} />
        <CopyButton label="Copy as plain text" getText={() => api<string>(`/v1/analyses/${id}/export`, { query: { format: "txt" }, text: true })} />
        <Button variant="ghost" onClick={() => void exportJson(id)}>
          JSON
        </Button>
      </div>

      <dl className="animate-fade mt-8 flex flex-wrap gap-x-8 gap-y-3" style={{ animationDelay: "500ms" }}>
        <Stat label="Requests">{a.entry_count}</Stat>
        <Stat label="Failed">{a.stats?.failed ?? "—"}</Stat>
        <Stat label="Hosts">{a.stats?.host_count ?? "—"}</Stat>
        <Stat label="Uploaded">{bytes(a.original_size_bytes)}</Stat>
        <Stat label="Deleted">
          <span title={dateTime(a.expires_at)}>{relative(a.expires_at)}</span>
        </Stat>
        {a.engine_version && <Stat label="Engine">{a.engine_version}</Stat>}
      </dl>

      <div className="animate-fade mt-6 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[8px] bg-paper-2 px-4 py-3 text-sm" style={{ animationDelay: "560ms" }}>
        <span aria-hidden="true" className="redaction">
          redacted
        </span>
        <span className="text-ink-2" data-testid="redaction-sentence">
          {r.sentence}
        </span>
        {secrets.map(([k, v]) => (
          <span key={k} className="rounded-full bg-card px-2 py-0.5 text-xs font-bold text-ink-2">
            {v} {LABELS[k]?.[v === 1 ? 0 : 1] ?? k}
          </span>
        ))}
        <span className="basis-full text-xs text-ink-3">Secret values were never stored. The same marker in two requests means the same value was sent in both.</span>
      </div>
    </section>
  );
}

function Row({ label, children, testId }: { label: string; children: React.ReactNode; testId?: string }) {
  return (
    <div className="grid gap-1 border-t border-rule py-4 first:border-t-0 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-6">
      <dt className="text-sm font-bold text-ink-3">{label}</dt>
      <dd className="min-w-0 text-base text-ink" data-testid={testId}>
        {children}
      </dd>
    </div>
  );
}

function Details({ summary }: { summary: Summary }) {
  const internal = kbPath(summary.kb_url);
  return (
    <section id="details" aria-labelledby="details-heading" className="scroll-mt-28 pt-12">
      <h2 id="details-heading" className="mb-2 font-display text-2xl font-medium">
        Details
      </h2>
      <dl className="max-w-4xl">
        <Row label="First failure" testId="first-failure">
          <span className="font-mono text-sm">
            <Redacted text={summary.first_failure} />
          </span>
        </Row>
        <Row label="Evidence">
          <ul className="space-y-1.5 font-mono text-sm text-ink-2">
            {summary.evidence.map((line) => (
              <li key={line}>
                <Redacted text={line} />
              </li>
            ))}
          </ul>
        </Row>
        <Row label="Customer was">
          <ul className="space-y-0.5">
            {summary.activity.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </Row>
        <Row label="KB article">
          {internal ? (
            <Link className={LINK} to={internal}>
              {summary.kb_title}
            </Link>
          ) : (
            <a className={LINK} href={summary.kb_url} target="_blank" rel="noreferrer noopener">
              {summary.kb_title} ↗
            </a>
          )}
        </Row>
      </dl>
      {summary.notes.map((n) => (
        <p key={n} className="mt-3 max-w-4xl rounded-[6px] bg-medium/15 px-4 py-2.5 text-sm">
          {n}
        </p>
      ))}
    </section>
  );
}

const SEVERITY_EDGE: Record<Finding["severity"], string> = {
  critical: "before:bg-critical",
  high: "before:bg-high",
  medium: "before:bg-medium",
  info: "before:bg-info",
};

function FindingItem({ finding, index, onShow }: { finding: Finding; index: number; onShow: () => void }) {
  return (
    <li
      className={`animate-rise relative overflow-hidden rounded-[8px] border border-rule bg-card p-5 pl-6 transition-shadow duration-150 before:absolute before:inset-y-0 before:left-0 before:w-1 hover:shadow-[0_2px_10px_rgb(0_0_0/0.06)] ${SEVERITY_EDGE[finding.severity]}`}
      style={{ animationDelay: `${Math.min(index, 8) * 40}ms` }}
      data-testid="finding"
    >
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={finding.severity} />
        <span className="font-mono text-xs text-ink-3">{finding.rule_id}</span>
        {finding.confidence === "likely" && <Tag tone="warn">likely</Tag>}
      </div>
      <p className="mt-2.5 font-display text-xl leading-snug font-medium">{finding.title}</p>
      <p className="mt-1.5 text-base text-ink-2">
        <Redacted text={finding.cause} />
      </p>
      {finding.evidence_lines && finding.evidence_lines.length > 0 && (
        <ul className="mt-3 space-y-1 rounded-[6px] bg-paper-2 px-3 py-2.5 font-mono text-xs text-ink-2">
          {finding.evidence_lines.map((line) => (
            <li key={line}>
              <Redacted text={line} />
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-base">
        <span className="font-bold text-ink-3">Next step: </span>
        {finding.next_step}
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-4">
        {finding.entries.length > 0 && (
          <Button size="sm" onClick={onShow}>
            Show {finding.entries.length} request{finding.entries.length === 1 ? "" : "s"}
          </Button>
        )}
        <Link to={`/kb/${finding.kb}`} className={`text-sm ${LINK}`}>
          KB article →
        </Link>
      </div>
    </li>
  );
}
