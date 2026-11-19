import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef, useState } from "react";
import { PHASE_LABEL, PHASES, bytes, ms, phaseDurations, shortUrl, statusTone } from "../lib/format";
import type { EntryRow } from "../lib/types";
import { cx } from "./ui";

const ROW = 30;
const MAX_HEIGHT = 30 * ROW;
const PHASE_CLASS: Record<string, string> = {
  blocked: "bg-phase-blocked",
  dns: "bg-phase-dns",
  connect: "bg-phase-connect",
  ssl: "bg-phase-ssl",
  send: "bg-phase-send",
  wait: "bg-phase-wait",
  receive: "bg-phase-receive",
};
const STATUS_CLASS = { green: "text-s2xx", amber: "text-s4xx font-medium", red: "text-s5xx font-bold", slate: "text-s3xx" };
const COLS = "grid-cols-[2.75rem_3.5rem_3.25rem_minmax(8rem,1fr)_4rem_4.5rem_minmax(6rem,26%)] max-md:grid-cols-[2rem_2.75rem_2.75rem_minmax(5rem,1fr)_3.5rem] max-md:gap-x-1.5 max-md:px-2";

export interface WaterfallFilter {
  failedOnly: boolean;
  host: string;
  minMs: number | null;
  text: string;
  numbers: Set<number> | null;
}

export const NO_FILTER: WaterfallFilter = { failedOnly: false, host: "", minMs: null, text: "", numbers: null };

export function isFiltered(f: WaterfallFilter): boolean {
  return Boolean(f.numbers || f.failedOnly || f.host || f.minMs !== null || f.text.trim());
}

export function applyFilter(rows: EntryRow[], f: WaterfallFilter): EntryRow[] {
  const text = f.text.trim().toLowerCase();
  return rows.filter(
    (r) =>
      (!f.failedOnly || r.failed) &&
      (!f.host || r.host === f.host) &&
      (f.minMs === null || r.time_ms >= f.minMs) &&
      (!text || r.url.toLowerCase().includes(text) || String(r.status).startsWith(text)) &&
      (!f.numbers || f.numbers.has(r.number)),
  );
}

/** A DevTools-style timeline. Virtualised: only the rows on screen are rendered,
 *  so a file with 50,000 requests scrolls as smoothly as one with 50. */
export function Waterfall({ rows, selected, onSelect, highlight, pulse }: { rows: EntryRow[]; selected: number | null; onSelect: (n: number) => void; highlight: Set<number>; pulse?: Set<number> }) {
  const parent = useRef<HTMLDivElement>(null);
  const span = useMemo(() => {
    let end = 0;
    for (const r of rows) end = Math.max(end, (r.started_ms ?? 0) + r.time_ms);
    return Math.max(end, 1);
  }, [rows]);
  // Bars grow from their start time once, on first render; rows that scroll into view later
  // just appear.
  const [intro, setIntro] = useState(true);
  useEffect(() => {
    const timer = window.setTimeout(() => setIntro(false), 1700);
    return () => window.clearTimeout(timer);
  }, []);
  const virtualizer = useVirtualizer({ count: rows.length, getScrollElement: () => parent.current, estimateSize: () => ROW, overscan: 12 });
  // As tall as the rows need, up to 30 rows; then it scrolls.
  const height = Math.min(Math.max(rows.length, 1) * ROW, MAX_HEIGHT);

  return (
    <div className="animate-rise overflow-hidden rounded-[8px] border border-rule bg-card">
      <div className={cx("grid gap-2 border-b border-rule bg-paper-2 px-3 py-2.5", COLS)} role="row">
        <span className="colhead">#</span>
        <span className="colhead">Method</span>
        <span className="colhead">Status</span>
        <span className="colhead">URL</span>
        <span className="colhead text-right">Size</span>
        <span className="colhead text-right max-md:hidden">Time</span>
        <span className="colhead max-md:hidden">Timeline · {ms(span)}</span>
      </div>
      <div ref={parent} className="overflow-auto" style={{ height }} role="table" aria-label="Requests" data-testid="waterfall">
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((item) => {
            const r = rows[item.index];
            if (!r) return null;
            const tone = statusTone(r.status, r.error);
            const phases = phaseDurations(r.timings);
            const left = ((r.started_ms ?? 0) / span) * 100;
            const width = Math.max((r.time_ms / span) * 100, 0.4);
            const total = PHASES.reduce((sum, p) => sum + (phases[p] ?? 0), 0) || r.time_ms || 1;
            const isSelected = selected === r.number;
            return (
              <button
                type="button"
                key={r.number}
                role="row"
                aria-selected={isSelected}
                onClick={() => onSelect(r.number)}
                className={cx(
                  "absolute left-0 grid w-full items-center gap-2 border-b border-l-[3px] border-b-rule/70 px-3 text-left font-mono text-xs transition-colors duration-150",
                  COLS,
                  isSelected
                    ? "border-l-primary bg-signal-soft"
                    : highlight.has(r.number)
                      ? "border-l-medium bg-medium/10 hover:bg-medium/20"
                      : "border-l-transparent hover:bg-paper-2",
                  pulse?.has(r.number) && "pulse-row",
                )}
                style={{ top: 0, height: ROW, transform: `translateY(${item.start}px)` }}
              >
                <span className="text-ink-3 tabular-nums">{r.number}</span>
                <span>{r.method}</span>
                <span title={r.error || undefined}>
                  <span className={cx("tabular-nums", STATUS_CLASS[tone])}>{r.status || "ERR"}</span>
                </span>
                <span className="truncate" title={r.url}>
                  <span className="text-ink-4">{r.host}</span>
                  <span className="text-ink">{shortUrl(r.url)}</span>
                </span>
                <span className="text-right text-ink-2 tabular-nums">{bytes(r.response_bytes)}</span>
                <span className="text-right text-ink-2 tabular-nums max-md:hidden">{ms(r.time_ms)}</span>
                <span className="relative h-3 w-full max-md:hidden" aria-hidden="true">
                  <span
                    className={cx("absolute top-0 flex h-3 overflow-hidden rounded-[2px]", intro && "animate-grow-x")}
                    // Each bar starts growing when the playhead reaches its real start time.
                    style={{ left: `${left}%`, width: `${width}%`, animationDelay: intro ? `${Math.round(left * 12)}ms` : undefined }}
                  >
                    {PHASES.map((p) =>
                      phases[p] ? <span key={p} className={PHASE_CLASS[p]} style={{ width: `${((phases[p] ?? 0) / total) * 100}%` }} /> : null,
                    )}
                    {r.status === 0 && <span className="h-full w-full bg-critical" />}
                  </span>
                  {intro && <span className="playhead" />}
                </span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 border-t border-rule px-3 py-2 text-xs text-ink-3">
        {PHASES.map((p) => (
          <span key={p} className="flex items-center gap-1.5">
            <span className={cx("inline-block h-2.5 w-2.5 rounded-[2px]", PHASE_CLASS[p])} />
            {PHASE_LABEL[p]}
          </span>
        ))}
      </div>
    </div>
  );
}
