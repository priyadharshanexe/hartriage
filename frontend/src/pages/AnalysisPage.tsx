import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { Magnetic, Reveal, RollingNumber, Spotlight, Stamp } from "../components/fx";
import { RequestDetail } from "../components/RequestDetail";
import { useToast } from "../components/Toasts";
import { Button, CopyButton, cx, EmptyState, ErrorState, Input, LoadingState, Notice, Redacted, Select, SeverityBadge, Tag } from "../components/ui";
import { NO_FILTER, Waterfall, type WaterfallFilter, applyFilter, isFiltered } from "../components/Waterfall";
import { api } from "../lib/api";
import { bytes, dateTime, relative } from "../lib/format";
import { EASE_OUT, POP } from "../lib/motion";
import { caseTitle } from "../lib/transition";
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
const EMPTY = new Set<number>();

export function AnalysisPage() {
  const { id = "" } = useParams();
  const { canEdit } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
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
  const [highlight, setHighlight] = useState<Set<number>>(EMPTY);
  // Hovering a finding lights up its requests in the waterfall; jumping to them pulses them.
  const [linked, setLinked] = useState<Set<number>>(EMPTY);
  const [pulse, setPulse] = useState<Set<number>>(EMPTY);
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
  const shown = useMemo(() => new Set([...highlight, ...linked]), [highlight, linked]);

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
    setPulse(new Set(f.entries));
    window.setTimeout(() => setPulse(EMPTY), 1900);
    document.getElementById("requests")?.scrollIntoView({ behavior: "smooth", block: "start" });
    open(f.entry);
  }

  function clearFilters() {
    setFilter(NO_FILTER);
    setHighlight(EMPTY);
  }

  async function rerun() {
    setRerunning(true);
    try {
      await api(`/v1/analyses/${id}/rerun`, { method: "POST" });
      open(null);
      clearFilters();
      setNotice(null);
      await queryClient.invalidateQueries({ queryKey: ["analysis", id] });
      toast("Re-running with the current rules…", "info");
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
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2 text-sm text-ink-3">
            <SourceBadge analysis={a} />
            <span>
              analysed <span title={dateTime(a.finished_at ?? a.created_at)}>{relative(a.finished_at ?? a.created_at)}</span>
            </span>
          </div>
          <h1 className="mt-2 font-mono text-lg font-medium break-words text-ink [overflow-wrap:anywhere]" style={caseTitle(a.id)}>
            {a.filename ?? "Analysis"}
          </h1>
        </div>
        {done && canEdit && (
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => void downloadRedacted(id, a.filename).then(() => toast("Redacted HAR downloaded. Its secrets are markers."), () => toast("The download failed.", "bad"))}>
              Download redacted HAR
            </Button>
            <Button size="sm" busy={rerunning || awaitingRerun} onClick={() => void rerun()}>
              {rerunning ? "Re-running…" : "Re-run analysis"}
            </Button>
          </div>
        )}
      </header>
      <AnimatePresence>
        {notice && (
          <div className="mt-4">
            <Notice tone={notice.tone} onDone={clearNotice}>
              {notice.text}
            </Notice>
          </div>
        )}
      </AnimatePresence>

      {a.status !== "done" ? (
        <div className="mt-8">
          {a.status === "failed" ? <ErrorState error={new Error(a.error ?? "The analysis failed.")} /> : <LoadingState label={`Analysis ${a.status}…`} />}
        </div>
      ) : (
        <>
          {a.summary && <Bento id={id} analysis={a} summary={a.summary} />}

          <nav
            aria-label="On this page"
            className="sticky top-[57px] z-10 -mx-4 mt-10 flex gap-1 overflow-x-auto border-y border-rule bg-paper/90 px-4 py-2 text-sm backdrop-blur-md sm:-mx-6 sm:px-6 md:top-0 md:-mx-10 md:px-10"
          >
            {[
              ["#answer", "Answer"],
              ["#details", "Details"],
              ["#findings", `Findings ${findingCount ?? ""}`],
              ["#requests", `Requests ${entries.data?.rows.length ?? ""}`],
            ].map(([href, label]) => (
              <a key={href} href={href} className="rounded-full px-3 py-1 whitespace-nowrap text-ink-3 transition-colors duration-150 hover:bg-raised hover:text-ink">
                {label}
              </a>
            ))}
          </nav>

          {a.summary && <Details summary={a.summary} />}

          <section id="findings" aria-labelledby="findings-heading" className="scroll-mt-28 pt-14">
            <Reveal>
              <h2 id="findings-heading" className="mb-1 flex items-baseline gap-3 font-display text-3xl font-semibold tracking-[-0.01em]">
                Findings <span className="font-mono text-lg font-normal text-ink-3">{findingCount ?? "…"}</span>
              </h2>
              <p className="mb-6 text-sm text-ink-3">Point at a finding to see its requests light up in the timeline below.</p>
            </Reveal>
            {findings.isPending ? (
              <LoadingState />
            ) : findings.isError ? (
              <ErrorState error={findings.error} onRetry={() => void findings.refetch()} />
            ) : findings.data.items.length === 0 ? (
              <EmptyState title="No findings">Every request succeeded and nothing was slow. The problem may not have been recorded.</EmptyState>
            ) : (
              <ol className="grid gap-3 xl:grid-cols-2">
                {findings.data.items.map((f, i) => (
                  <FindingItem
                    key={f.id}
                    finding={f}
                    index={i}
                    onShow={() => showRequests(f)}
                    onHover={(on) => setLinked(on ? new Set(f.entries) : EMPTY)}
                  />
                ))}
              </ol>
            )}
          </section>

          <section id="requests" aria-labelledby="requests-heading" className="scroll-mt-28 space-y-3 pt-14">
            <Reveal>
              <h2 id="requests-heading" className="flex items-baseline gap-3 font-display text-3xl font-semibold tracking-[-0.01em]">
                Requests
                <span className="font-mono text-lg font-normal text-ink-3">
                  {entries.data ? (filtered ? `${rows.length} of ${entries.data.rows.length}` : entries.data.rows.length) : "…"}
                </span>
              </h2>
            </Reveal>
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
              <Waterfall rows={rows} selected={selected} onSelect={open} highlight={shown} pulse={pulse} />
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

/** "Copy for ticket": the label morphs into a check, and a small "copied" token flies off. */
function CopyForTicket({ id }: { id: string }) {
  const reduce = useReducedMotion();
  const [state, setState] = useState<"idle" | "busy" | "done" | "failed">("idle");
  const [flights, setFlights] = useState<number[]>([]);
  async function copy() {
    setState("busy");
    try {
      await navigator.clipboard.writeText(await api<string>(`/v1/analyses/${id}/export`, { query: { format: "md" }, text: true }));
      setState("done");
      const key = Date.now();
      setFlights((f) => [...f, key]);
      window.setTimeout(() => setFlights((f) => f.filter((k) => k !== key)), 900);
    } catch {
      setState("failed");
    }
    window.setTimeout(() => setState("idle"), 2200);
  }
  return (
    <span className="relative inline-flex">
      <Magnetic>
        <motion.button
          type="button"
          layout
          onClick={() => void copy()}
          disabled={state === "busy"}
          className="inline-flex h-12 items-center gap-2.5 rounded-[8px] bg-primary px-5 text-base font-bold text-on-primary shadow-[0_8px_24px_-12px_var(--primary)] transition-[filter] hover:brightness-110 disabled:opacity-60"
          whileTap={reduce ? undefined : { scale: 0.96 }}
        >
          <AnimatePresence mode="popLayout" initial={false}>
            {state === "done" ? (
              <motion.span key="done" className="inline-flex items-center gap-2" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={POP}>
                <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
                  <motion.path d="M3 8.5l3.2 3L13 4.5" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.3 }} />
                </svg>
                Copied
              </motion.span>
            ) : (
              <motion.span key="idle" className="inline-flex items-center gap-2" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={POP}>
                <svg viewBox="0 0 16 16" className="h-4 w-4" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8">
                  <rect x="4" y="3" width="9" height="11" rx="1.5" />
                  <path d="M6.5 3V2h4v1" />
                </svg>
                {state === "failed" ? "Copy failed" : "Copy for ticket"}
              </motion.span>
            )}
          </AnimatePresence>
        </motion.button>
      </Magnetic>
      {!reduce &&
        flights.map((k) => (
          <motion.span
            key={k}
            aria-hidden="true"
            className="pointer-events-none absolute top-1 left-1/2 rounded-full bg-highlight px-2 py-0.5 font-mono text-[0.7rem] font-bold text-highlight-ink"
            initial={{ opacity: 1, x: "-50%", y: 0, scale: 0.9 }}
            animate={{ opacity: 0, x: "40%", y: -46, scale: 1, rotate: -6 }}
            transition={{ duration: 0.8, ease: EASE_OUT }}
          >
            summary.md
          </motion.span>
        ))}
    </span>
  );
}

function Tile({ children, className, delay = 0, label }: { children: React.ReactNode; className?: string; delay?: number; label?: string }) {
  const reduce = useReducedMotion();
  return (
    <motion.div
      className={cx("rounded-[16px] border border-rule bg-card p-5", className)}
      initial={reduce ? false : { opacity: 0, y: 18, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ type: "spring", stiffness: 260, damping: 26, delay }}
    >
      {label && <p className="text-sm font-bold text-ink-3">{label}</p>}
      {children}
    </motion.div>
  );
}

/** The answer page, as tiles of different weight: the cause first, then the evidence. */
function Bento({ id, analysis: a, summary }: { id: string; analysis: Analysis; summary: Summary }) {
  const r = a.redaction;
  const secrets = Object.entries(r.secrets ?? {}).filter(([, v]) => v > 0);
  const failed = a.stats?.failed ?? 0;
  return (
    <section id="answer" aria-labelledby="answer-heading" className="mt-8 scroll-mt-28">
      <div className="grid gap-3 lg:grid-cols-12">
        <Tile className="relative overflow-hidden p-6 sm:p-8 lg:col-span-8 lg:row-span-2">
          <h2 id="answer-heading" className="text-sm font-bold text-ink-3">
            Likely cause
          </h2>
          <p className="mt-4 font-display text-[2rem] leading-[1.12] font-semibold tracking-[-0.015em] text-ink sm:text-[2.75rem]" data-testid="likely-cause">
            <span className="highlighter">
              <Redacted text={summary.likely_cause} />
            </span>
          </p>
          <motion.div className="mt-7 flex max-w-3xl gap-3" initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: 0.55, duration: 0.35, ease: EASE_OUT }}>
            <span aria-hidden="true" className="mt-1 font-bold text-signal">
              →
            </span>
            <p className="text-lg leading-snug text-ink-2">
              <span className="sr-only">Next step: </span>
              {summary.next_step}
            </p>
          </motion.div>
          <motion.div className="mt-8 flex flex-wrap items-center gap-2" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.7, duration: 0.3, ease: EASE_OUT }}>
            <CopyForTicket id={id} />
            <CopyButton label="Copy as plain text" getText={() => api<string>(`/v1/analyses/${id}/export`, { query: { format: "txt" }, text: true })} />
            <Button variant="ghost" onClick={() => void exportJson(id)}>
              JSON
            </Button>
          </motion.div>
        </Tile>

        <Tile className="grid grid-cols-2 gap-4 lg:col-span-4" delay={0.08}>
          {[
            ["Requests", a.entry_count, "text-ink"],
            ["Failed", failed, failed ? "text-critical" : "text-ink"],
            ["Hosts", a.stats?.host_count ?? 0, "text-ink"],
            ["Seconds", Math.round(a.stats?.duration_seconds ?? 0), "text-ink"],
          ].map(([label, value, tone]) => (
            <div key={String(label)}>
              <p className="text-xs text-ink-3">{label}</p>
              <p className={cx("mt-1 font-display text-4xl leading-none font-semibold", String(tone))}>
                <RollingNumber value={Number(value)} />
              </p>
            </div>
          ))}
          <p className="col-span-2 border-t border-rule pt-3 text-xs text-ink-3">
            {bytes(a.original_size_bytes)} uploaded · deleted <span title={dateTime(a.expires_at)}>{relative(a.expires_at)}</span>
            {a.engine_version && <> · engine {a.engine_version}</>}
          </p>
        </Tile>

        <Tile className="lg:col-span-4" delay={0.16} label="Removed before storage">
          <ul className="mt-3 space-y-2">
            {secrets.length === 0 && <li className="text-sm text-ink-3">No credentials in this file.</li>}
            {secrets.map(([k, v], i) => (
              <li key={k} className="flex items-center justify-between gap-3">
                <span className="font-mono text-sm">
                  <Stamp marker={LABELS[k]?.[v === 1 ? 0 : 1] ?? k} delay={300 + i * 250} length={8} />
                </span>
                <span className="font-display text-2xl font-semibold">
                  <RollingNumber value={v} />
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs leading-relaxed text-ink-3" data-testid="redaction-sentence">
            {r.sentence}
          </p>
        </Tile>

        <Tile className="lg:col-span-12" delay={0.24} label="First failure">
          <p className="mt-2 font-mono text-sm text-ink-2" data-testid="first-failure">
            <Redacted text={summary.first_failure} />
          </p>
        </Tile>
      </div>
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-1 border-t border-rule py-4 first:border-t-0 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-6">
      <dt className="text-sm font-bold text-ink-3">{label}</dt>
      <dd className="min-w-0 text-base text-ink">{children}</dd>
    </div>
  );
}

function Details({ summary }: { summary: Summary }) {
  const internal = kbPath(summary.kb_url);
  return (
    <section id="details" aria-labelledby="details-heading" className="scroll-mt-28 pt-14">
      <Reveal>
        <h2 id="details-heading" className="mb-2 font-display text-3xl font-semibold tracking-[-0.01em]">
          Details
        </h2>
      </Reveal>
      <Reveal delay={0.08}>
        <dl className="max-w-4xl">
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
      </Reveal>
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

function FindingItem({ finding, index, onShow, onHover }: { finding: Finding; index: number; onShow: () => void; onHover: (on: boolean) => void }) {
  const reduce = useReducedMotion();
  return (
    <motion.li
      initial={reduce ? false : { opacity: 0, y: 20 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-40px" }}
      transition={{ type: "spring", stiffness: 300, damping: 30, delay: Math.min(index, 6) * 0.05 }}
      onPointerEnter={() => onHover(true)}
      onPointerLeave={() => onHover(false)}
      onFocus={() => onHover(true)}
      onBlur={() => onHover(false)}
      data-testid="finding"
    >
      <Spotlight
        className={`relative h-full overflow-hidden rounded-[14px] border border-rule bg-card p-5 pl-6 transition-[border-color,transform] duration-200 before:absolute before:inset-y-0 before:left-0 before:w-1 hover:-translate-y-0.5 hover:border-rule-2 ${SEVERITY_EDGE[finding.severity]}`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <motion.span initial={reduce ? false : { scale: 0.4, opacity: 0 }} whileInView={{ scale: 1, opacity: 1 }} viewport={{ once: true }} transition={{ ...POP, delay: Math.min(index, 6) * 0.05 + 0.1 }}>
            <SeverityBadge severity={finding.severity} />
          </motion.span>
          <span className="font-mono text-xs text-ink-3">{finding.rule_id}</span>
          {finding.confidence === "likely" && <Tag tone="warn">likely</Tag>}
          {finding.entries.length > 0 && <span className="ml-auto font-mono text-xs text-ink-4">{finding.entries.map((n) => `#${n}`).slice(0, 6).join(" ")}</span>}
        </div>
        <p className="mt-3 font-display text-[1.375rem] leading-snug font-semibold">{finding.title}</p>
        <p className="mt-1.5 text-base text-ink-2">
          <Redacted text={finding.cause} />
        </p>
        {finding.evidence_lines && finding.evidence_lines.length > 0 && (
          <ul className="mt-3 space-y-1 rounded-[8px] bg-paper-2 px-3 py-2.5 font-mono text-xs text-ink-2">
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
      </Spotlight>
    </motion.li>
  );
}
