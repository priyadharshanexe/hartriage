import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { RequestDetail } from "../components/RequestDetail";
import { Badge, Button, Card, CopyButton, EmptyState, ErrorState, Input, LoadingState, PageHeader, Redacted, Select, SeverityBadge } from "../components/ui";
import { Waterfall, type WaterfallFilter, applyFilter } from "../components/Waterfall";
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
  const [filter, setFilter] = useState<WaterfallFilter>({ failedOnly: false, host: "", minMs: null, text: "", numbers: null });
  const [highlight, setHighlight] = useState<Set<number>>(new Set());
  const rows = useMemo(() => applyFilter(entries.data?.rows ?? [], filter), [entries.data, filter]);

  if (analysis.isPending) return <LoadingState />;
  if (analysis.isError) return <ErrorState error={analysis.error} onRetry={() => void analysis.refetch()} />;
  const a = analysis.data;

  function showRequests(f: Finding) {
    setFilter({ failedOnly: false, host: "", minMs: null, text: "", numbers: new Set(f.entries) });
    setHighlight(new Set(f.entries));
    setSelected(f.entry);
    document.getElementById("requests")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function rerun() {
    await api(`/v1/analyses/${id}/rerun`, { method: "POST" });
    await queryClient.invalidateQueries({ queryKey: ["analysis", id] });
    await queryClient.invalidateQueries({ queryKey: ["findings", id] });
    await queryClient.invalidateQueries({ queryKey: ["entries", id] });
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={a.filename ?? "Analysis"}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <SourceBadge analysis={a} />
            <span>{a.entry_count} requests</span>·<span>{bytes(a.original_size_bytes)} uploaded</span>·
            <span title={dateTime(a.created_at)}>analysed {relative(a.created_at)}</span>·
            <span title={dateTime(a.expires_at)}>deleted {relative(a.expires_at)}</span>
            {a.engine_version && <Badge>engine {a.engine_version}</Badge>}
          </span>
        }
        action={
          done && (
            <>
              {canEdit && (
                <a className="inline-flex items-center rounded-md bg-white px-3.5 py-2 text-sm font-medium text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50" href={`/v1/analyses/${id}/redacted.har`} onClick={(e) => { e.preventDefault(); void downloadRedacted(id, a.filename); }}>
                  Download redacted HAR
                </a>
              )}
              {canEdit && <Button onClick={() => void rerun()}>Re-run analysis</Button>}
            </>
          )
        }
      />

      {a.status !== "done" ? (
        a.status === "failed" ? (
          <ErrorState error={new Error(a.error ?? "The analysis failed.")} />
        ) : (
          <LoadingState label={`Analysis ${a.status}…`} />
        )
      ) : (
        <>
          {a.summary && <SummaryCard id={id} summary={a.summary} />}
          <RedactionCard analysis={a} />
          <Card title={`Findings (${findings.data?.items.length ?? "…"})`}>
            {findings.isPending ? (
              <LoadingState />
            ) : findings.isError ? (
              <ErrorState error={findings.error} />
            ) : findings.data.items.length === 0 ? (
              <EmptyState title="No findings">Every request succeeded and nothing was slow. The problem may not have been recorded.</EmptyState>
            ) : (
              <ol className="divide-y divide-slate-100">
                {findings.data.items.map((f) => (
                  <FindingItem key={f.id} finding={f} onShow={() => showRequests(f)} />
                ))}
              </ol>
            )}
          </Card>

          <section id="requests" className="space-y-3">
            <div className="flex flex-wrap items-end gap-3">
              <h2 className="mr-auto text-base font-semibold">Requests</h2>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={filter.failedOnly} onChange={(e) => setFilter({ ...filter, failedOnly: e.target.checked, numbers: null })} />
                Failed only
              </label>
              <div className="w-52"><Select aria-label="Host" value={filter.host} onChange={(e) => setFilter({ ...filter, host: e.target.value, numbers: null })}>
                <option value="">All hosts</option>
                {entries.data?.hosts.map((h) => (
                  <option key={h.host} value={h.host}>
                    {h.host} ({h.count})
                  </option>
                ))}
              </Select></div>
              <div className="w-40"><Input aria-label="Slower than (ms)" type="number" min={0} placeholder="Slower than (ms)" value={filter.minMs ?? ""} onChange={(e) => setFilter({ ...filter, minMs: e.target.value === "" ? null : Number(e.target.value), numbers: null })} /></div>
              <div className="w-52"><Input aria-label="Search URLs" placeholder="Search URL or status" value={filter.text} onChange={(e) => setFilter({ ...filter, text: e.target.value, numbers: null })} /></div>
              {(filter.numbers || filter.failedOnly || filter.host || filter.minMs !== null || filter.text) && (
                <Button size="sm" variant="ghost" onClick={() => { setFilter({ failedOnly: false, host: "", minMs: null, text: "", numbers: null }); setHighlight(new Set()); }}>
                  Clear filters
                </Button>
              )}
            </div>
            {filter.numbers && <p className="text-xs text-slate-500">Showing the {filter.numbers.size} request(s) of one finding.</p>}
            <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_28rem]">
              {entries.isPending ? <LoadingState /> : entries.isError ? <ErrorState error={entries.error} /> : <Waterfall rows={rows} selected={selected} onSelect={setSelected} highlight={highlight} />}
              {selected !== null && <RequestDetail analysisId={id} number={selected} onClose={() => setSelected(null)} />}
            </div>
          </section>
        </>
      )}
    </div>
  );
}

async function downloadRedacted(id: string, filename: string | null) {
  const text = await api<string>(`/v1/analyses/${id}/redacted.har`, { text: true });
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${(filename ?? "file.har").replace(/\.[^.]+$/, "")}.redacted.har`;
  link.click();
  URL.revokeObjectURL(url);
}

function SummaryCard({ id, summary }: { id: string; summary: Summary }) {
  return (
    <Card
      title="Ticket summary"
      action={
        <div className="flex flex-wrap gap-2">
          <CopyButton variant="primary" label="Copy for ticket" getText={() => api<string>(`/v1/analyses/${id}/export`, { query: { format: "md" }, text: true })} />
          <CopyButton label="Copy as plain text" getText={() => api<string>(`/v1/analyses/${id}/export`, { query: { format: "txt" }, text: true })} />
          <Button size="md" variant="ghost" onClick={() => void exportJson(id)}>
            JSON
          </Button>
        </div>
      }
    >
      <dl className="space-y-3 text-sm">
        <div>
          <dt className="font-medium text-slate-500">What the customer was doing</dt>
          <dd>
            <ul className="list-disc pl-5">
              {summary.activity.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </dd>
        </div>
        <div>
          <dt className="font-medium text-slate-500">First failure</dt>
          <dd className="break-all font-mono text-xs" data-testid="first-failure"><Redacted text={summary.first_failure} /></dd>
        </div>
        <div>
          <dt className="font-medium text-slate-500">Likely cause</dt>
          <dd className="text-base font-medium text-slate-900" data-testid="likely-cause"><Redacted text={summary.likely_cause} /></dd>
        </div>
        <div>
          <dt className="font-medium text-slate-500">Evidence</dt>
          <dd>
            <ul className="list-disc pl-5 font-mono text-xs">
              {summary.evidence.map((line) => (
                <li key={line} className="break-all"><Redacted text={line} /></li>
              ))}
            </ul>
          </dd>
        </div>
        <div>
          <dt className="font-medium text-slate-500">Suggested next step</dt>
          <dd>{summary.next_step}</dd>
        </div>
        <div>
          <dt className="font-medium text-slate-500">KB article</dt>
          <dd>
            <a className="text-brand-700 underline" href={summary.kb_url} target="_blank" rel="noreferrer noopener">
              {summary.kb_title}
            </a>
          </dd>
        </div>
        {summary.notes.map((n) => (
          <p key={n} className="rounded bg-amber-50 px-3 py-2 text-amber-900">{n}</p>
        ))}
      </dl>
    </Card>
  );
}

async function exportJson(id: string) {
  const text = await api<string>(`/v1/analyses/${id}/export`, { query: { format: "json" }, text: true });
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "analysis.json";
  link.click();
  URL.revokeObjectURL(url);
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

function RedactionCard({ analysis }: { analysis: Analysis }) {
  const r = analysis.redaction;
  return (
    <Card title="Redaction report">
      <p className="text-sm text-slate-700" data-testid="redaction-sentence">{r.sentence}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {Object.entries(r.secrets ?? {}).map(([k, v]) => (
          <Badge key={k} tone="amber">{v} {LABELS[k]?.[v === 1 ? 0 : 1] ?? k}</Badge>
        ))}
        {(r.response_bodies_removed ?? 0) > 0 && <Badge>{r.response_bodies_removed} response {r.response_bodies_removed === 1 ? "body" : "bodies"} dropped</Badge>}
        {(r.error_bodies_kept ?? 0) > 0 && <Badge tone="blue">{r.error_bodies_kept} small error {r.error_bodies_kept === 1 ? "body" : "bodies"} kept</Badge>}
        {(r.request_bodies_removed ?? 0) > 0 && <Badge>{r.request_bodies_removed} large request bodies dropped</Badge>}
      </div>
      <p className="mt-3 text-xs text-slate-500">
        Secret values were never stored. The same marker in two requests means the same value was sent in both.
      </p>
    </Card>
  );
}

function FindingItem({ finding, onShow }: { finding: Finding; onShow: () => void }) {
  return (
    <li className="py-3" data-testid="finding">
      <div className="flex flex-wrap items-start gap-2">
        <SeverityBadge severity={finding.severity} />
        <Badge>{finding.rule_id}</Badge>
        {finding.confidence === "likely" && <Badge tone="slate">likely</Badge>}
        <p className="min-w-0 flex-1 font-medium text-slate-900">{finding.title}</p>
      </div>
      <p className="mt-1 text-sm text-slate-700"><Redacted text={finding.cause} /></p>
      <p className="mt-1 text-sm text-slate-500">
        <span className="font-medium text-slate-600">Next step:</span> {finding.next_step}
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        {finding.entries.length > 0 && (
          <Button size="sm" onClick={onShow}>
            Show {finding.entries.length} request{finding.entries.length === 1 ? "" : "s"}
          </Button>
        )}
        <Link to={`/kb/${finding.kb}`} className="inline-flex items-center rounded-md px-2.5 py-1 text-xs font-medium text-brand-700 hover:bg-brand-50">
          KB article →
        </Link>
      </div>
    </li>
  );
}
