import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { api } from "../lib/api";
import { PHASE_LABEL, PHASES, bytes, epoch, ms } from "../lib/format";
import type { EntryDetail, NameValue } from "../lib/types";
import { ErrorState, LoadingState, Redacted, Tag } from "./ui";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-rule px-5 py-4">
      <h3 className="mb-2.5 text-sm font-bold text-ink-3">{title}</h3>
      {children}
    </section>
  );
}

function Pairs({ items, empty = "None" }: { items: NameValue[] | undefined; empty?: string }) {
  if (!items || items.length === 0) return <p className="text-xs text-ink-4">{empty}</p>;
  return (
    <dl className="grid grid-cols-[minmax(7rem,32%)_1fr] gap-x-3 gap-y-1.5 font-mono text-xs">
      {items.map((h, i) => (
        <div key={`${h.name}-${i}`} className="contents">
          <dt className="min-w-0 break-words text-ink-3 [overflow-wrap:anywhere]">{h.name}</dt>
          <dd className="min-w-0 text-ink">
            <Redacted text={String(h.value)} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** The request detail, as a drawer over the right side of the page. */
export function RequestDetail({ analysisId, number, onClose }: { analysisId: string; number: number; onClose: () => void }) {
  const query = useQuery({
    queryKey: ["entry", analysisId, number],
    queryFn: () => api<EntryDetail>(`/v1/analyses/${analysisId}/entries/${number}`),
  });
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus({ preventScroll: true });
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, number]);

  // Rendered into <body>: the page's entry animation transforms its container, and a
  // transformed ancestor would pin this "fixed" drawer to the container, not the window.
  return createPortal(
    <>
      <div className="animate-fade fixed inset-0 z-40 bg-black/30" onClick={onClose} aria-hidden="true" />
      <aside
        className="animate-slide-in-right fixed inset-y-0 right-0 z-50 flex w-full max-w-xl flex-col border-l border-rule bg-card shadow-[-16px_0_40px_-16px_rgb(0_0_0/0.35)]"
        aria-label={`Request ${number}`}
      >
        <div className="flex items-center justify-between border-b border-rule px-5 py-3.5">
          <h2 className="font-display text-xl font-medium">
            Request <span className="font-mono text-lg">#{number}</span>
          </h2>
          <button ref={closeRef} type="button" onClick={onClose} aria-label="Close request detail" className="rounded-[5px] px-2 py-1 text-sm text-ink-3 transition-colors hover:bg-paper-2 hover:text-ink">
            Esc ✕
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {query.isPending ? (
            <LoadingState />
          ) : query.isError ? (
            <div className="p-5">
              <ErrorState error={query.error} />
            </div>
          ) : (
            <Body detail={query.data} />
          )}
        </div>
      </aside>
    </>,
    document.body,
  );
}

function Body({ detail }: { detail: EntryDetail }) {
  const { entry, meta } = detail;
  const req = entry.request;
  const res = entry.response;
  const error = (entry._error as string | undefined) ?? ((res as Record<string, unknown>)._failureText as string | undefined);
  const timings = entry.timings ?? {};
  const total = PHASES.reduce((s, p) => s + Math.max(timings[p] ?? 0, 0), 0) || 1;
  const failed = res.status >= 400 || res.status <= 0;
  return (
    <div className="text-sm">
      <div className="px-5 py-4">
        <p className="font-mono text-xs">
          <span className="font-semibold">{req.method}</span> <Redacted text={req.url} />
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Tag tone={failed ? "bad" : "ok"}>{res.status > 0 ? `${res.status} ${res.statusText ?? ""}` : "No response"}</Tag>
          {error && <Tag tone="bad">{error}</Tag>}
          {res.httpVersion && <Tag>{res.httpVersion}</Tag>}
          {entry.serverIPAddress && <Tag>{entry.serverIPAddress}</Tag>}
          <Tag tone={meta.credentials_present ? "ink" : "muted"}>{meta.credentials_present ? `credentials: ${meta.credentials?.join(", ")}` : "No credentials sent"}</Tag>
        </div>
      </div>

      <Section title="Timing">
        <div className="space-y-1.5">
          {PHASES.map((p) => {
            const value = timings[p];
            if (value === undefined || value === null || value < 0) return null;
            return (
              <div key={p} className="grid grid-cols-[7rem_1fr_4.5rem] items-center gap-3 text-xs">
                <span className="text-ink-3">{PHASE_LABEL[p]}</span>
                <span className="h-2 bg-paper-2">
                  <span className={`block h-2 bg-phase-${p}`} style={{ width: `${Math.min(100, (value / total) * 100)}%` }} />
                </span>
                <span className="text-right font-mono tabular-nums">{ms(value)}</span>
              </div>
            );
          })}
        </div>
      </Section>

      {meta.jwts && meta.jwts.length > 0 && (
        <Section title="Tokens · claims read before redaction">
          <ul className="space-y-2 font-mono text-xs">
            {meta.jwts.map((j) => {
              const started = entry.startedDateTime ? Date.parse(entry.startedDateTime) / 1000 : null;
              const expired = j.exp !== null && started !== null && j.exp < started;
              return (
                <li key={j.marker} className="leading-relaxed">
                  <Redacted text={j.marker} /> in {j.location}
                  <br />
                  exp {epoch(j.exp)} {expired && <Tag tone="bad">expired before this request</Tag>}
                  {j.iat !== null && <> · iat {epoch(j.iat)}</>}
                  {j.aud.length > 0 && <> · aud {j.aud.join(", ")}</>}
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {meta.correlation_ids && Object.keys(meta.correlation_ids).length > 0 && (
        <Section title="Correlation ids · for engineering">
          <Pairs items={Object.entries(meta.correlation_ids).map(([name, value]) => ({ name, value }))} />
        </Section>
      )}

      <Section title="Request headers">
        <Pairs items={req.headers} />
      </Section>
      {req.queryString && req.queryString.length > 0 && (
        <Section title="Query string">
          <Pairs items={req.queryString} />
        </Section>
      )}
      {req.cookies && req.cookies.length > 0 && (
        <Section title="Cookies sent">
          <Pairs items={req.cookies.map((c) => ({ name: c.name, value: c.value }))} />
        </Section>
      )}
      {req.postData && (
        <Section title={`Request body · ${req.postData.mimeType ?? "unknown type"}`}>
          {req.postData.text ? (
            <pre className="max-h-56 overflow-auto bg-paper-2 p-3 font-mono text-xs whitespace-pre-wrap">
              <Redacted text={req.postData.text} />
            </pre>
          ) : (
            <p className="text-xs text-ink-3">{req.postData.comment ?? "Empty"}</p>
          )}
        </Section>
      )}
      <Section title="Response headers">
        <Pairs items={res.headers} />
      </Section>
      <Section title="Response body">
        <p className="mb-2 font-mono text-xs text-ink-3">
          {res.content?.mimeType || "unknown type"} · {bytes(res.content?.size)}
        </p>
        {res.content?.text ? (
          <pre className="max-h-56 overflow-auto bg-paper-2 p-3 font-mono text-xs whitespace-pre-wrap">
            <Redacted text={res.content.text} />
          </pre>
        ) : (
          <p className="text-xs text-ink-3">{res.content?.comment ?? "No body recorded."}</p>
        )}
      </Section>
    </div>
  );
}
