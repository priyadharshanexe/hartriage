import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { RequestDetail } from "../components/RequestDetail";
import { Button, CopyButton, EmptyState, ErrorState, Input, LoadingState, Notice, PageHeader, Redacted, Select, SeverityBadge, Stat, Tag } from "../components/ui";
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

const LINK = "underline decoration-signal decoration-2 underline-offset-2 hover:text-signal";

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
          <Link to="/analyses" className="inline-flex h-7 items-center border border-ink/80 px-2.5 text-xs font-medium hover:bg-ink hover:text-paper">
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
    <div className="space-y-10">
      <PageHeader
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            Case file <SourceBadge analysis={a} />
          </span>
        }
        title={<span className="break-words">{a.filename ?? "Analysis"}</span>}
        action={
          done &&
          canEdit && (
            <>
              <Button onClick={() => void downloadRedacted(id, a.filename)}>Download redacted HAR</Button>
              <Button busy={rerunning || awaitingRerun} onClick={() => void rerun()}>
                {rerunning ? "Re-running…" : "Re-run analysis"}
              </Button>
            </>
          )
        }
      />
      {notice && (
        <Notice tone={notice.tone} onDone={clearNotice}>
          {notice.text}
        </Notice>
      )}

      {a.status !== "done" ? (
        a.status === "failed" ? (
          <ErrorState error={new Error(a.error ?? "The analysis failed.")} />
        ) : (
          <LoadingState label={`Analysis ${a.status}…`} />
        )
      ) : (
        <>
          <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_18rem]">
            {a.summary ? <SummaryBlock id={id} summary={a.summary} /> : <div />}
            <div className="space-y-8">
              <dl className="grid grid-cols-2 gap-x-4 gap-y-4 border-t-2 border-ink pt-4">
                <Stat label="Requests">{a.entry_count}</Stat>
                <Stat label="Failed">{a.stats?.failed ?? "—"}</Stat>
                <Stat label="Hosts">{a.stats?.host_count ?? "—"}</Stat>
                <Stat label="Uploaded">{bytes(a.original_size_bytes)}</Stat>
                <Stat label="Analysed">
                  <span title={dateTime(a.finished_at ?? a.created_at)}>{relative(a.finished_at ?? a.created_at)}</span>
                </Stat>
                <Stat label="Deleted">
                  <span title={dateTime(a.expires_at)}>{relative(a.expires_at)}</span>
                </Stat>
                {a.engine_version && <Stat label="Engine">{a.engine_version}</Stat>}
              </dl>
              <RedactionBlock analysis={a} />
            </div>
          </div>

          <section aria-labelledby="findings-heading">
            <h2 id="findings-heading" className="mb-4 flex items-baseline gap-3 border-b border-ink pb-2 font-display text-xl font-semibold">
              Findings <span className="font-mono text-sm font-normal text-ink-3">{findingCount ?? "…"}</span>
            </h2>
            {findings.isPending ? (
              <LoadingState />
            ) : findings.isError ? (
              <ErrorState error={findings.error} onRetry={() => void findings.refetch()} />
            ) : findings.data.items.length === 0 ? (
              <EmptyState title="No findings">Every request succeeded and nothing was slow. The problem may not have been recorded.</EmptyState>
            ) : (
              <ol className="space-y-3">
                {findings.data.items.map((f) => (
                  <FindingItem key={f.id} finding={f} onShow={() => showRequests(f)} />
                ))}
              </ol>
            )}
          </section>

          <section id="requests" aria-labelledby="requests-heading" className="space-y-3">
            <h2 id="requests-heading" className="flex items-baseline gap-3 border-b border-ink pb-2 font-display text-xl font-semibold">
              Requests
              <span className="font-mono text-sm font-normal text-ink-3">
                {entries.data ? (filtered ? `${rows.length} of ${entries.data.rows.length}` : entries.data.rows.length) : "…"}
              </span>
            </h2>
            <div className="flex flex-wrap items-center gap-3">
              <label className="flex h-9 items-center gap-2 border border-rule-2 bg-card px-3 text-sm">
                <input type="checkbox" className="accent-ink" checked={filter.failedOnly} onChange={(e) => setFilter({ ...filter, failedOnly: e.target.checked, numbers: null })} />
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
              <p className="border-l-4 border-medium bg-medium/10 px-3 py-1.5 text-xs">
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

function Row({ label, children, testId }: { label: string; children: React.ReactNode; testId?: string }) {
  return (
    <div className="grid gap-1 border-t border-rule py-3 sm:grid-cols-[10rem_minmax(0,1fr)] sm:gap-4">
      <dt className="eyebrow pt-0.5">{label}</dt>
      <dd className="min-w-0 text-sm text-ink" data-testid={testId}>
        {children}
      </dd>
    </div>
  );
}

function SummaryBlock({ id, summary }: { id: string; summary: Summary }) {
  const internal = kbPath(summary.kb_url);
  return (
    <section aria-labelledby="summary-heading">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="summary-heading" className="eyebrow text-signal">
          Ticket summary
        </h2>
        <div className="flex flex-wrap gap-2">
          <CopyButton variant="primary" label="Copy for ticket" getText={() => api<string>(`/v1/analyses/${id}/export`, { query: { format: "md" }, text: true })} />
          <CopyButton label="Copy as plain text" getText={() => api<string>(`/v1/analyses/${id}/export`, { query: { format: "txt" }, text: true })} />
          <Button variant="ghost" onClick={() => void exportJson(id)}>
            JSON
          </Button>
        </div>
      </div>
      <p className="mt-4 font-display text-[1.7rem] leading-tight font-semibold tracking-tight text-ink" data-testid="likely-cause">
        <Redacted text={summary.likely_cause} />
      </p>
      <dl className="mt-6">
        <Row label="First failure" testId="first-failure">
          <span className="font-mono text-xs">
            <Redacted text={summary.first_failure} />
          </span>
        </Row>
        <Row label="Next step">
          <span className="font-medium">{summary.next_step}</span>
        </Row>
        <Row label="Evidence">
          <ul className="space-y-1 font-mono text-xs">
            {summary.evidence.map((line) => (
              <li key={line} className="border-l-2 border-rule-2 pl-2.5">
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
        <p key={n} className="mt-3 border-l-4 border-medium bg-medium/15 px-3 py-2 text-sm">
          {n}
        </p>
      ))}
    </section>
  );
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

function RedactionBlock({ analysis }: { analysis: Analysis }) {
  const r = analysis.redaction;
  const secrets = Object.entries(r.secrets ?? {}).filter(([, v]) => v > 0);
  return (
    <section aria-labelledby="redaction-heading" className="bg-ink p-4 text-paper">
      <h2 id="redaction-heading" className="eyebrow text-[#8a8475]">
        Redaction report
      </h2>
      <p className="mt-2 text-sm leading-snug" data-testid="redaction-sentence">
        {r.sentence}
      </p>
      {secrets.length > 0 && (
        <ul className="mt-3 space-y-1 font-mono text-xs">
          {secrets.map(([k, v]) => (
            <li key={k} className="flex items-center justify-between gap-2">
              <span className="redaction">{LABELS[k]?.[v === 1 ? 0 : 1] ?? k}</span>
              <span className="tabular-nums">{v}</span>
            </li>
          ))}
        </ul>
      )}
      <ul className="mt-3 space-y-0.5 text-xs text-[#b8b19f]">
        {(r.response_bodies_removed ?? 0) > 0 && <li>{r.response_bodies_removed} response {r.response_bodies_removed === 1 ? "body" : "bodies"} dropped</li>}
        {(r.error_bodies_kept ?? 0) > 0 && <li>{r.error_bodies_kept} small error {r.error_bodies_kept === 1 ? "body" : "bodies"} kept</li>}
        {(r.request_bodies_removed ?? 0) > 0 && <li>{r.request_bodies_removed} large request bodies dropped</li>}
      </ul>
      <p className="mt-3 border-t border-white/10 pt-3 text-xs text-[#8a8475]">Secret values were never stored. The same marker in two requests means the same value was sent in both.</p>
    </section>
  );
}

const SEVERITY_RULE: Record<Finding["severity"], string> = {
  critical: "border-l-critical",
  high: "border-l-high",
  medium: "border-l-medium",
  info: "border-l-info",
};

function FindingItem({ finding, onShow }: { finding: Finding; onShow: () => void }) {
  return (
    <li className={`border border-l-4 border-rule bg-card p-4 ${SEVERITY_RULE[finding.severity]}`} data-testid="finding">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={finding.severity} />
        <Tag>{finding.rule_id}</Tag>
        {finding.confidence === "likely" && <Tag tone="warn">likely</Tag>}
      </div>
      <p className="mt-2 font-display text-lg leading-snug font-semibold">{finding.title}</p>
      <p className="mt-1 text-sm text-ink-2">
        <Redacted text={finding.cause} />
      </p>
      {finding.evidence_lines && finding.evidence_lines.length > 0 && (
        <ul className="mt-3 space-y-1 bg-paper-2/70 px-3 py-2 font-mono text-xs text-ink-2">
          {finding.evidence_lines.map((line) => (
            <li key={line}>
              <Redacted text={line} />
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-sm">
        <span className="eyebrow mr-2">Next step</span>
        {finding.next_step}
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        {finding.entries.length > 0 && (
          <Button size="sm" onClick={onShow}>
            Show {finding.entries.length} request{finding.entries.length === 1 ? "" : "s"}
          </Button>
        )}
        <Link to={`/kb/${finding.kb}`} className={`text-xs font-medium ${LINK}`}>
          KB article →
        </Link>
      </div>
    </li>
  );
}
