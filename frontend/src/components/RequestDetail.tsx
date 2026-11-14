import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { api } from "../lib/api";
import { PHASE_LABEL, PHASES, bytes, epoch, ms } from "../lib/format";
import type { EntryDetail, NameValue } from "../lib/types";
import { Badge, Button, ErrorState, LoadingState, Redacted } from "./ui";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-slate-100 py-3">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
      {children}
    </section>
  );
}

function Pairs({ items, empty = "None" }: { items: NameValue[] | undefined; empty?: string }) {
  if (!items || items.length === 0) return <p className="text-xs text-slate-400">{empty}</p>;
  return (
    <dl className="grid grid-cols-[minmax(7rem,30%)_1fr] gap-x-3 gap-y-1 text-xs">
      {items.map((h, i) => (
        <div key={`${h.name}-${i}`} className="contents">
          <dt className="break-all font-mono text-slate-500">{h.name}</dt>
          <dd className="font-mono text-slate-800">
            <Redacted text={String(h.value)} />
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function RequestDetail({ analysisId, number, onClose }: { analysisId: string; number: number; onClose: () => void }) {
  const query = useQuery({
    queryKey: ["entry", analysisId, number],
    queryFn: () => api<EntryDetail>(`/v1/analyses/${analysisId}/entries/${number}`),
  });

  return (
    <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm" aria-label={`Request ${number}`}>
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Request #{number}</h2>
        <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close request detail">
          Close
        </Button>
      </div>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <ErrorState error={query.error} />
      ) : (
        <Body detail={query.data} />
      )}
    </aside>
  );
}

function Body({ detail }: { detail: EntryDetail }) {
  const { entry, meta } = detail;
  const req = entry.request;
  const res = entry.response;
  const error = (entry._error as string | undefined) ?? (res as Record<string, unknown>)._failureText as string | undefined;
  const timings = entry.timings ?? {};
  const total = PHASES.reduce((s, p) => s + Math.max(timings[p] ?? 0, 0), 0) || 1;
  return (
    <div className="text-sm">
      <p className="break-all font-mono text-xs">
        <span className="font-semibold">{req.method}</span> <Redacted text={req.url} />
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Badge tone={res.status >= 400 || res.status <= 0 ? "red" : "green"}>{res.status > 0 ? `${res.status} ${res.statusText ?? ""}` : "No response"}</Badge>
        {error && <Badge tone="red">{error}</Badge>}
        {res.httpVersion && <Badge>{res.httpVersion}</Badge>}
        {entry.serverIPAddress && <Badge>{entry.serverIPAddress}</Badge>}
        <Badge tone={meta.credentials_present ? "blue" : "slate"}>{meta.credentials_present ? `Credentials: ${meta.credentials?.join(", ")}` : "No credentials sent"}</Badge>
      </div>

      <Section title="Timing">
        <div className="space-y-1">
          {PHASES.map((p) => {
            const value = timings[p];
            if (value === undefined || value === null || value < 0) return null;
            return (
              <div key={p} className="grid grid-cols-[7rem_1fr_4rem] items-center gap-2 text-xs">
                <span className="text-slate-500">{PHASE_LABEL[p]}</span>
                <span className="h-2 rounded bg-slate-100">
                  <span className="block h-2 rounded bg-brand-500" style={{ width: `${Math.min(100, (value / total) * 100)}%` }} />
                </span>
                <span className="text-right tabular-nums">{ms(value)}</span>
              </div>
            );
          })}
        </div>
      </Section>

      {meta.jwts && meta.jwts.length > 0 && (
        <Section title="Tokens (claims read before redaction)">
          <ul className="space-y-1 text-xs">
            {meta.jwts.map((j) => {
              const started = entry.startedDateTime ? Date.parse(entry.startedDateTime) / 1000 : null;
              const expired = j.exp !== null && started !== null && j.exp < started;
              return (
                <li key={j.marker} className="font-mono">
                  <Redacted text={j.marker} /> in {j.location}: exp {epoch(j.exp)} {expired && <Badge tone="red">expired before this request</Badge>}
                  {j.iat !== null && <> · iat {epoch(j.iat)}</>}
                  {j.aud.length > 0 && <> · aud {j.aud.join(", ")}</>}
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {meta.correlation_ids && Object.keys(meta.correlation_ids).length > 0 && (
        <Section title="Correlation ids (for engineering)">
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
        <Section title={`Request body (${req.postData.mimeType ?? "unknown type"})`}>
          {req.postData.text ? (
            <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded bg-slate-50 p-2 font-mono text-xs">
              <Redacted text={req.postData.text} />
            </pre>
          ) : (
            <p className="text-xs text-slate-500">{req.postData.comment ?? "Empty"}</p>
          )}
        </Section>
      )}
      <Section title="Response headers">
        <Pairs items={res.headers} />
      </Section>
      <Section title="Response body">
        <p className="mb-1 text-xs text-slate-500">
          {res.content?.mimeType || "unknown type"} · {bytes(res.content?.size)}
        </p>
        {res.content?.text ? (
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all rounded bg-slate-50 p-2 font-mono text-xs">
            <Redacted text={res.content.text} />
          </pre>
        ) : (
          <p className="text-xs text-slate-500">{res.content?.comment ?? "No body recorded."}</p>
        )}
      </Section>
    </div>
  );
}
