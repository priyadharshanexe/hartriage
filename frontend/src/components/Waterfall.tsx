import { useVirtualizer } from "@tanstack/react-virtual";
import { useMemo, useRef } from "react";
import { PHASE_LABEL, PHASES, bytes, ms, phaseDurations, shortUrl, statusTone } from "../lib/format";
import type { EntryRow } from "../lib/types";
import { cx } from "./ui";

const ROW = 30;
const PHASE_CLASS: Record<string, string> = {
  blocked: "bg-phase-blocked",
  dns: "bg-phase-dns",
  connect: "bg-phase-connect",
  ssl: "bg-phase-ssl",
  send: "bg-phase-send",
  wait: "bg-phase-wait",
  receive: "bg-phase-receive",
};
const STATUS_CLASS = { green: "text-emerald-700", amber: "text-amber-700", red: "text-red-700 font-semibold", slate: "text-slate-500" };

export interface WaterfallFilter {
  failedOnly: boolean;
  host: string;
  minMs: number | null;
  text: string;
  numbers: Set<number> | null;
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
export function Waterfall({ rows, selected, onSelect, highlight }: { rows: EntryRow[]; selected: number | null; onSelect: (n: number) => void; highlight: Set<number> }) {
  const parent = useRef<HTMLDivElement>(null);
  const span = useMemo(() => {
    let end = 0;
    for (const r of rows) end = Math.max(end, (r.started_ms ?? 0) + r.time_ms);
    return Math.max(end, 1);
  }, [rows]);
  const virtualizer = useVirtualizer({ count: rows.length, getScrollElement: () => parent.current, estimateSize: () => ROW, overscan: 12 });

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="grid grid-cols-[2.75rem_3.5rem_3rem_minmax(10rem,1fr)_4rem_4.5rem_minmax(6rem,22%)] gap-2 border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs font-medium uppercase tracking-wide text-slate-500" role="row">
        <span>#</span>
        <span>Method</span>
        <span>Status</span>
        <span>URL</span>
        <span className="text-right">Size</span>
        <span className="text-right">Time</span>
        <span>Timeline ({ms(span)})</span>
      </div>
      <div ref={parent} className="h-[28rem] overflow-auto" role="table" aria-label="Requests" data-testid="waterfall">
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((item) => {
            const r = rows[item.index];
            if (!r) return null;
            const tone = statusTone(r.status, r.error);
            const phases = phaseDurations(r.timings);
            const left = ((r.started_ms ?? 0) / span) * 100;
            const width = Math.max((r.time_ms / span) * 100, 0.4);
            const total = PHASES.reduce((sum, p) => sum + (phases[p] ?? 0), 0) || r.time_ms || 1;
            return (
              <button
                type="button"
                key={r.number}
                role="row"
                aria-selected={selected === r.number}
                onClick={() => onSelect(r.number)}
                className={cx(
                  "absolute left-0 grid w-full grid-cols-[2.75rem_3.5rem_3rem_minmax(10rem,1fr)_4rem_4.5rem_minmax(6rem,22%)] items-center gap-2 border-b border-slate-50 px-3 text-left text-xs hover:bg-slate-50",
                  selected === r.number && "bg-brand-50 hover:bg-brand-50",
                  highlight.has(r.number) && selected !== r.number && "bg-amber-50/60",
                )}
                style={{ top: 0, height: ROW, transform: `translateY(${item.start}px)` }}
              >
                <span className="tabular-nums text-slate-500">{r.number}</span>
                <span className="font-mono">{r.method}</span>
                <span className={cx("tabular-nums", STATUS_CLASS[tone])} title={r.error || undefined}>
                  {r.status || "ERR"}
                </span>
                <span className="truncate" title={r.url}>
                  <span className="text-slate-400">{r.host}</span> {shortUrl(r.url)}
                </span>
                <span className="text-right tabular-nums text-slate-600">{bytes(r.response_bytes)}</span>
                <span className="text-right tabular-nums text-slate-600">{ms(r.time_ms)}</span>
                <span className="relative h-3 w-full" aria-hidden="true">
                  <span className="absolute top-0 flex h-3 overflow-hidden rounded-sm" style={{ left: `${left}%`, width: `${width}%` }}>
                    {PHASES.map((p) =>
                      phases[p] ? <span key={p} className={PHASE_CLASS[p]} style={{ width: `${((phases[p] ?? 0) / total) * 100}%` }} /> : null,
                    )}
                    {r.status === 0 && <span className="h-full w-full bg-red-400" />}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      </div>
      <div className="flex flex-wrap gap-3 border-t border-slate-100 px-3 py-2 text-xs text-slate-500">
        {PHASES.map((p) => (
          <span key={p} className="flex items-center gap-1">
            <span className={cx("inline-block h-2.5 w-2.5 rounded-sm", PHASE_CLASS[p])} />
            {PHASE_LABEL[p]}
          </span>
        ))}
      </div>
    </div>
  );
}
