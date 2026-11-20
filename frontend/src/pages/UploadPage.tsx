import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
import { type DragEvent, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { DrawCheck, Magnetic, RollingNumber, Scramble, Spotlight, Stamp } from "../components/fx";
import { Button, cx, ErrorState, Redacted } from "../components/ui";
import { api, uploadFile } from "../lib/api";
import { bytes, relative, shortUrl } from "../lib/format";
import { EASE_OUT, POP, reducedMotion } from "../lib/motion";
import { caseTitle, useTransitionNavigate } from "../lib/transition";
import type { Analysis, EntriesPage, EntryDetail, EntryRow, Finding, KbItem, Severity } from "../lib/types";

const ACCEPT = ".har,.json,.gz,.zip";
const MAX_BYTES = 100 * 1024 * 1024;

const SECRET_LABELS: Record<string, [string, string]> = {
  tokens: ["token", "tokens"],
  cookies: ["cookie", "cookies"],
  api_keys: ["API key", "API keys"],
  passwords: ["password", "passwords"],
  signatures: ["signature", "signatures"],
  aws_keys: ["AWS key", "AWS keys"],
  private_keys: ["private key", "private keys"],
};
const MARKER = /\[REDACTED:([0-9a-f]{8})\]/;

// ------------------------------------------------------------------ the empty page

/** A looping, clearly labelled sample: a request's secrets being stamped out. */
const SAMPLE: { name: string; before: string; marker?: string; after?: string }[] = [
  { name: ":method", before: "POST /api/checkout" },
  { name: "authorization", before: "Bearer ", marker: "3f9a01c2" },
  { name: "cookie", before: "session=", marker: "b71e04aa", after: "; theme=dark" },
  { name: "x-api-key", before: "", marker: "0c55e9d1" },
  { name: "x-request-id", before: "req_8c1d42" },
  { name: "body.password", before: "", marker: "9e02f3b7" },
];

function SampleLoop() {
  const reduce = useReducedMotion();
  const [cycle, setCycle] = useState(0);
  useEffect(() => {
    if (reduce) return;
    const timer = window.setInterval(() => setCycle((c) => c + 1), 6500);
    return () => window.clearInterval(timer);
  }, [reduce]);
  let stamp = 0;
  return (
    <figure className="relative overflow-hidden rounded-[14px] border border-rule bg-raised p-5 sm:p-6" aria-label="Sample: a request's secrets being replaced with markers">
      <figcaption className="flex items-center justify-between gap-3">
        <span className="inline-flex items-center gap-2 rounded-full border border-dashed border-rule-2 px-2.5 py-0.5 text-xs font-bold tracking-wide text-ink-3">
          Sample
        </span>
        <span className="text-xs text-ink-4">not your data</span>
      </figcaption>
      <div key={cycle} className="mt-5 space-y-2.5 font-mono text-[0.8125rem] leading-6">
        {SAMPLE.map((line, i) => (
          <motion.div
            key={line.name}
            className="grid grid-cols-[8.5rem_minmax(0,1fr)] gap-3"
            initial={reduce ? false : { opacity: 0, x: -10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: reduce ? 0 : i * 0.12, duration: 0.3, ease: EASE_OUT }}
          >
            <span className="truncate text-ink-4">{line.name}</span>
            <span className="min-w-0 truncate text-ink-2">
              {line.before}
              {line.marker && <Stamp marker={line.marker} delay={900 + stamp++ * 650} length={10} />}
              {line.after}
            </span>
          </motion.div>
        ))}
      </div>
      <p className="mt-5 border-t border-rule pt-4 text-sm text-ink-3">
        Every secret is replaced as the file streams in. The same value always gets the same marker, so you can still follow it.
      </p>
    </figure>
  );
}

function RecentCases() {
  const go = useTransitionNavigate();
  const recent = useQuery({ queryKey: ["analyses", "recent"], queryFn: () => api<{ items: Analysis[] }>("/v1/analyses", { query: { limit: 4 } }) });
  const items = recent.data?.items ?? [];
  if (items.length === 0) return null;
  return (
    <section aria-labelledby="recent-heading" className="mt-14">
      <div className="flex items-baseline justify-between">
        <h2 id="recent-heading" className="font-display text-2xl font-medium">
          Recent cases
        </h2>
        <Link to="/analyses" className="text-sm font-bold text-signal hover:underline">
          All history →
        </Link>
      </div>
      <ul className="mt-5 grid gap-3 sm:grid-cols-2">
        {items.map((a, i) => (
          <motion.li key={a.id} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * i, duration: 0.35, ease: EASE_OUT }}>
            <Spotlight className="h-full rounded-[12px] border border-rule bg-card transition-colors duration-150 hover:border-rule-2">
              <a
                href={`/analyses/${a.id}`}
                onClick={(e) => {
                  e.preventDefault();
                  go(`/analyses/${a.id}`);
                }}
                className="block h-full p-5"
              >
                <span className="flex items-center justify-between gap-3 text-xs text-ink-4">
                  <span>{relative(a.finished_at ?? a.created_at)}</span>
                  <span>{a.entry_count} requests</span>
                </span>
                <span className="mt-2 block truncate font-mono text-sm font-medium text-ink" style={caseTitle(a.id)}>
                  {a.filename ?? "file.har"}
                </span>
                <span className="mt-2 line-clamp-2 block text-sm text-ink-2">{a.lead ? <Redacted text={a.lead} /> : "No failures found"}</span>
              </a>
            </Spotlight>
          </motion.li>
        ))}
      </ul>
    </section>
  );
}

// ------------------------------------------------------------------ the show

const SEVERITY_TEXT: Record<Severity, string> = { critical: "text-critical", high: "text-high", medium: "text-medium-ink", info: "text-info" };
const SEVERITY_BG: Record<Severity, string> = { critical: "bg-critical", high: "bg-high", medium: "bg-medium", info: "bg-info" };

function statusClass(r: EntryRow): string {
  if (r.status === 0 || r.error || r.status >= 500) return "bg-critical/15 text-s5xx";
  if (r.status >= 400) return "bg-medium/15 text-s4xx";
  if (r.status >= 300) return "bg-s3xx/15 text-s3xx";
  return "bg-ok/12 text-s2xx";
}

interface ShowData {
  rows: EntryRow[];
  findings: Finding[];
  secrets: { request: number; name: string; prefix: string; marker: string }[];
  rules: KbItem[];
}

/** Everything the replay shows is read back from the finished analysis. */
async function loadShow(id: string): Promise<ShowData> {
  const [entries, findings, kb] = await Promise.all([
    api<EntriesPage>(`/v1/analyses/${id}/entries`, { query: { limit: 40 } }),
    api<{ items: Finding[] }>(`/v1/analyses/${id}/findings`),
    api<{ items: KbItem[] }>("/v1/kb").catch(() => ({ items: [] as KbItem[] })),
  ]);
  const details = await Promise.all(
    entries.items.slice(0, 8).map((r) => api<EntryDetail>(`/v1/analyses/${id}/entries/${r.number}`).catch(() => null)),
  );
  const secrets: ShowData["secrets"] = [];
  const seen = new Set<string>();
  for (const d of details) {
    if (!d) continue;
    for (const h of [...(d.entry.request.headers ?? []), ...(d.entry.request.queryString ?? [])]) {
      const m = MARKER.exec(String(h.value));
      if (m && m[1] && !seen.has(`${h.name}:${m[1]}`)) {
        seen.add(`${h.name}:${m[1]}`);
        secrets.push({ request: d.number, name: h.name.toLowerCase(), prefix: String(h.value).slice(0, m.index).slice(-24), marker: m[1] });
      }
    }
  }
  return { rows: entries.items, findings: findings.items, secrets: secrets.slice(0, 6), rules: kb.items.filter((k) => k.rule_id).sort((a, b) => String(a.rule_id).localeCompare(String(b.rule_id))) };
}

function RedactionShow({ analysis, data, onOpen }: { analysis: Analysis; data: ShowData; onOpen: () => void }) {
  const reduce = useReducedMotion();
  const rows = data.rows.slice(0, 18);
  const secrets = Object.entries(analysis.redaction.secrets ?? {}).filter(([, v]) => v > 0);
  const t = {
    stamps: 0.15 + rows.length * 0.04,
    rules: 0.6 + rows.length * 0.04 + data.secrets.length * 0.32,
  };
  const answerAt = t.rules + data.rules.length * 0.09 + 0.4;
  const byRule = useMemo(() => {
    const map = new Map<string, Finding[]>();
    for (const f of data.findings) map.set(f.rule_id, [...(map.get(f.rule_id) ?? []), f]);
    return map;
  }, [data.findings]);
  const worst = (fs: Finding[]): Severity => (["critical", "high", "medium", "info"] as Severity[]).find((s) => fs.some((f) => f.severity === s)) ?? "info";

  return (
    <div className="grid gap-4 lg:grid-cols-12">
      {/* 1. The real requests, streaming past */}
      <section className="rounded-[14px] border border-rule bg-card p-4 lg:col-span-5" aria-label="Requests in the file">
        <header className="flex items-baseline justify-between px-1">
          <h3 className="text-sm font-bold text-ink-3">Requests read</h3>
          <span className="font-mono text-lg font-medium">
            <RollingNumber value={analysis.entry_count} />
          </span>
        </header>
        <ol className="mt-3 space-y-1 font-mono text-xs">
          {rows.map((r, i) => (
            <motion.li
              key={r.number}
              className="grid grid-cols-[2rem_3rem_minmax(0,1fr)_3rem] items-center gap-2 rounded-[6px] px-1 py-1"
              initial={reduce ? false : { opacity: 0, y: 10, filter: "blur(4px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              transition={{ delay: reduce ? 0 : 0.04 * i, duration: 0.28, ease: EASE_OUT }}
            >
              <span className="text-ink-4">{r.number}</span>
              <span className="text-ink-3">{r.method}</span>
              <span className="truncate">
                <span className="text-ink-4">{r.host}</span>
                <span className="text-ink-2">{shortUrl(r.url)}</span>
              </span>
              <span className={cx("justify-self-end rounded-full px-1.5 text-center font-medium", statusClass(r))}>{r.status || "ERR"}</span>
            </motion.li>
          ))}
        </ol>
      </section>

      <div className="grid gap-4 lg:col-span-7">
        {/* 2. Secrets being stamped out (real marker ids from the redacted copy) */}
        <section className="rounded-[14px] border border-rule bg-card p-5" aria-label="Secrets removed">
          <header className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-bold text-ink-3">Secrets removed while it uploaded</h3>
            <span className="text-xs text-ink-4">replayed: the values were never stored</span>
          </header>
          <ul className="mt-4 space-y-2 font-mono text-[0.8125rem]">
            {data.secrets.length === 0 && <li className="text-ink-3">No credentials in the first requests.</li>}
            {data.secrets.map((s, i) => (
              <motion.li
                key={`${s.name}-${s.marker}`}
                className="grid grid-cols-[2.25rem_9rem_minmax(0,1fr)] items-center gap-2"
                initial={reduce ? false : { opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: reduce ? 0 : t.stamps + i * 0.32 }}
              >
                <span className="text-ink-4">#{s.request}</span>
                <span className="truncate text-ink-3">{s.name}</span>
                <span className="truncate text-ink-2">
                  {s.prefix}
                  <Stamp marker={s.marker} delay={reduce ? 0 : (t.stamps + i * 0.32) * 1000} />
                </span>
              </motion.li>
            ))}
          </ul>
          <dl className="mt-5 flex flex-wrap gap-x-6 gap-y-2 border-t border-rule pt-4">
            {secrets.map(([k, v]) => (
              <div key={k} className="flex items-baseline gap-1.5">
                <dd className="font-mono text-2xl font-medium">
                  <RollingNumber value={v} />
                </dd>
                <dt className="text-sm text-ink-3">{SECRET_LABELS[k]?.[v === 1 ? 0 : 1] ?? k}</dt>
              </div>
            ))}
            {(analysis.redaction.response_bodies_removed ?? 0) > 0 && (
              <div className="flex items-baseline gap-1.5">
                <dd className="font-mono text-2xl font-medium">
                  <RollingNumber value={analysis.redaction.response_bodies_removed ?? 0} />
                </dd>
                <dt className="text-sm text-ink-3">response bodies dropped</dt>
              </div>
            )}
          </dl>
        </section>

        {/* 3. The rules running */}
        <section className="rounded-[14px] border border-rule bg-card p-5" aria-label="Rules">
          <h3 className="text-sm font-bold text-ink-3">Checks</h3>
          <ul className="mt-3 grid gap-1.5 sm:grid-cols-2">
            {data.rules.map((rule, i) => {
              const hits = byRule.get(String(rule.rule_id)) ?? [];
              const delay = reduce ? 0 : t.rules + i * 0.09;
              return (
                <motion.li
                  key={rule.slug}
                  className={cx("flex items-center gap-2 rounded-[8px] border px-2.5 py-1.5 text-xs", hits.length ? "border-transparent bg-raised" : "border-rule")}
                  initial={reduce ? false : { opacity: 0.25 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay, duration: 0.2 }}
                  title={rule.title}
                >
                  {hits.length ? (
                    <motion.span
                      className={cx("grid h-5 min-w-5 place-items-center rounded-full px-1 text-[0.65rem] font-bold text-white", SEVERITY_BG[worst(hits)], worst(hits) === "medium" && "text-[#0b0d10]")}
                      initial={reduce ? false : { scale: 0 }}
                      animate={{ scale: 1 }}
                      transition={{ ...POP, delay }}
                    >
                      {hits.length}
                    </motion.span>
                  ) : (
                    <span className="text-ok">
                      <DrawCheck delay={delay} />
                    </span>
                  )}
                  <span className="font-mono text-ink-3">{rule.rule_id}</span>
                  <span className={cx("leading-tight", hits.length ? cx("font-bold", SEVERITY_TEXT[worst(hits)]) : "text-ink-3")}>{rule.title}</span>
                </motion.li>
              );
            })}
          </ul>
        </section>
      </div>

      {/* 4. The answer */}
      <motion.section
        className="rounded-[14px] border border-rule bg-card p-6 lg:col-span-12"
        initial={reduce ? false : { opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: reduce ? 0 : answerAt, duration: 0.4, ease: EASE_OUT }}
        aria-live="polite"
      >
        <p className="text-sm font-bold text-ink-3">Likely cause</p>
        <p className="mt-2 font-display text-2xl leading-snug font-semibold sm:text-3xl">
          <span className="highlighter" style={{ animationDelay: `${(reduce ? 0 : answerAt) * 1000 + 250}ms` }}>
            {analysis.lead ? <Redacted text={analysis.lead} /> : "No failures found in this recording."}
          </span>
        </p>
        <div className="mt-5">
          <Magnetic>
            <Button variant="primary" onClick={onOpen}>
              Open the analysis →
            </Button>
          </Magnetic>
        </div>
      </motion.section>
    </div>
  );
}

// ------------------------------------------------------------------ the page

function UploadProgress({ file, progress, analysis }: { file: File | null; progress: number; analysis: Analysis | undefined }) {
  const pct = Math.round(progress * 100);
  const secrets = Object.entries(analysis?.redaction.secrets ?? {}).filter(([, v]) => v > 0);
  return (
    <div className="rounded-[14px] border border-rule bg-card p-6 sm:p-8">
      <p className="font-mono text-sm text-ink-3">
        <Scramble text={`${file?.name ?? "file.har"} · ${bytes(file?.size)}`} duration={500} />
      </p>
      <div className="mt-6 flex items-end gap-4">
        <span className="font-display text-6xl leading-none font-semibold tabular-nums">
          <RollingNumber value={analysis ? 100 : pct} />
          <span className="text-3xl text-ink-3">%</span>
        </span>
        <span className="pb-1.5 text-sm text-ink-3">{analysis ? "Read and redacted. Running the checks…" : "Reading the file and replacing secrets as it streams in…"}</span>
      </div>
      <div className="mt-5 h-2 overflow-hidden rounded-full bg-paper-2" role="progressbar" aria-label="Upload progress" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <motion.div className="h-full rounded-full bg-primary" animate={{ width: `${analysis ? 100 : pct}%` }} transition={{ type: "spring", stiffness: 120, damping: 24 }} />
      </div>
      {analysis && (
        <ul className="mt-6 flex flex-wrap gap-x-6 gap-y-2 text-sm">
          <li className="text-ink-3">Removed so far:</li>
          {secrets.length === 0 && <li className="text-ink-2">no credentials</li>}
          {secrets.map(([k, v]) => (
            <li key={k} className="flex items-baseline gap-1.5">
              <span className="font-mono text-lg font-medium">
                <RollingNumber value={v} />
              </span>
              <span className="text-ink-3">{SECRET_LABELS[k]?.[v === 1 ? 0 : 1] ?? k}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function UploadPage() {
  const { canEdit } = useAuth();
  const go = useTransitionNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<unknown>(null);
  // The organisation's size limit (an admin may set one below the server's).
  const limits = useQuery({ queryKey: ["org-settings"], queryFn: () => api<{ effective_max_file_mb: number }>("/v1/org/settings"), staleTime: 60_000 });
  const maxMb = limits.data?.effective_max_file_mb ?? MAX_BYTES / (1024 * 1024);
  const maxBytes = maxMb * 1024 * 1024;
  const [analysisId, setAnalysisId] = useState<string | null>(null);

  const status = useQuery({
    queryKey: ["analysis", analysisId],
    queryFn: () => api<Analysis>(`/v1/analyses/${analysisId}`),
    enabled: analysisId !== null,
    refetchInterval: (q) => (q.state.data && ["done", "failed"].includes(q.state.data.status) ? false : 600),
  });
  const done = status.data?.status === "done" ? status.data : null;
  const show = useQuery({ queryKey: ["show", done?.id], queryFn: () => loadShow(done!.id), enabled: done !== null && !reducedMotion() });

  // Reduced motion: no replay, straight to the answer.
  useEffect(() => {
    if (done && reducedMotion()) go(`/analyses/${done.id}`);
  }, [done, go]);
  // After the replay, open the analysis by itself.
  useEffect(() => {
    if (!done || !show.data) return;
    const length = 1.6 + Math.min(show.data.rows.length, 18) * 0.04 + show.data.secrets.length * 0.32 + show.data.rules.length * 0.09 + 2.4;
    const timer = window.setTimeout(() => go(`/analyses/${done.id}`), length * 1000);
    return () => window.clearTimeout(timer);
  }, [done, show.data, go]);
  useEffect(() => {
    if (show.isError && done) go(`/analyses/${done.id}`);
  }, [show.isError, done, go]);

  async function start(chosen: File) {
    setFile(chosen);
    setError(null);
    setAnalysisId(null);
    if (chosen.size > maxBytes) {
      // Checked here first: there is no point uploading 100 MB only to be refused.
      setError(new Error(`${chosen.name} is ${bytes(chosen.size)}; the limit is ${maxMb} MB. Ask the customer to record a shorter session, or use the CLI.`));
      return;
    }
    setProgress(0);
    try {
      const result = await uploadFile(chosen, setProgress);
      setAnalysisId(result.analysis_id);
    } catch (e) {
      setError(e);
      setProgress(null);
    }
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files[0];
    if (dropped) void start(dropped);
  }

  const failed = status.data?.status === "failed";
  const busy = progress !== null && !error && !failed;

  return (
    <div>
      <AnimatePresence mode="wait" initial={false}>
        {busy ? (
          <motion.div key="busy" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.25, ease: EASE_OUT }}>
            <h1 className="font-display text-4xl font-semibold tracking-[-0.02em]">{done ? "Here is what we found" : "Analysing…"}</h1>
            <p className="mt-2 text-ink-3">Analyse a HAR file · {file?.name}</p>
            <div className="mt-8">
              {done && show.data ? <RedactionShow analysis={done} data={show.data} onOpen={() => go(`/analyses/${done.id}`)} /> : <UploadProgress file={file} progress={progress ?? 0} analysis={status.data} />}
            </div>
          </motion.div>
        ) : (
          <motion.div key="idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.2 }}>
            <div className="grid items-stretch gap-6 lg:grid-cols-12">
              <div className="flex flex-col lg:col-span-7">
                <h1 className="font-display text-[2.6rem] leading-[1.05] font-semibold tracking-[-0.02em] sm:text-[3.4rem]">Analyse a HAR file</h1>
                <p className="mt-4 max-w-xl text-lg text-ink-2">
                  Drop the file a customer sent. The secrets come out while it uploads; you get the failing request, the likely cause and a summary for the ticket.
                </p>
                {!canEdit && <div className="animate-slide-down mt-5 rounded-[8px] bg-medium/15 px-4 py-3 text-sm">Viewers can read analyses but not upload files.</div>}
                {error !== null && (
                  <div className="mt-5">
                    <ErrorState error={error} />
                  </div>
                )}
                <div
                  onDragOver={(e) => {
                    e.preventDefault();
                    if (canEdit) setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={canEdit ? onDrop : (e) => e.preventDefault()}
                  className={cx(
                    "group relative mt-8 flex flex-1 flex-col justify-between overflow-hidden rounded-[16px] border-2 border-dashed p-6 transition-[border-color,background-color] duration-200 sm:p-8",
                    dragging ? "border-primary bg-signal-soft" : "border-rule-2 bg-card",
                  )}
                >
                  <motion.div animate={{ scale: dragging ? 1.02 : 1 }} transition={POP} className="origin-left">
                    <p className="font-display text-3xl font-medium">{dragging ? "Let go to start." : "Drop it here."}</p>
                    <p className="mt-2 text-sm text-ink-3">.har, .har.gz, or a zip with one HAR inside · up to {maxMb} MB and 50,000 requests</p>
                  </motion.div>
                  <div className="mt-10 flex flex-wrap items-center gap-4">
                    <Magnetic>
                      <Button variant="primary" className="h-12 px-6 text-base" disabled={!canEdit} onClick={() => input.current?.click()}>
                        Choose a file
                      </Button>
                    </Magnetic>
                    <span className="text-sm text-ink-3">
                      or run <code className="rounded bg-paper-2 px-1.5 py-0.5 font-mono text-xs text-ink-2">hartriage analyze file.har</code> offline
                    </span>
                  </div>
                  <input
                    ref={input}
                    type="file"
                    accept={ACCEPT}
                    className="hidden"
                    data-testid="file-input"
                    onChange={(e) => {
                      const chosen = e.target.files?.[0];
                      e.target.value = ""; // choosing the same file again should start again
                      if (chosen) void start(chosen);
                    }}
                  />
                </div>
              </div>
              <div className="lg:col-span-5">
                <SampleLoop />
                <p className="mt-4 px-1 text-sm text-ink-3">
                  Only the redacted copy is stored, encrypted, and deleted when it expires. Nothing is sent to any AI service. Customer asking how to record one? Send them{" "}
                  <Link className="font-bold text-signal hover:underline" to="/kb/recording-a-har">
                    recording a useful HAR file
                  </Link>
                  .
                </p>
              </div>
            </div>
            <RecentCases />
          </motion.div>
        )}
      </AnimatePresence>
      {failed && (
        <div className="mt-4">
          <ErrorState error={new Error(status.data?.error ?? "The analysis failed.")} />
        </div>
      )}
    </div>
  );
}
