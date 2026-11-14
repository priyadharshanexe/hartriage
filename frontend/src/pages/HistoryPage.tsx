import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Button, EmptyState, ErrorState, Input, LoadingState, PageHeader, Redacted, Tag } from "../components/ui";
import { api } from "../lib/api";
import { bytes, dateTime, relative } from "../lib/format";
import type { Analysis } from "../lib/types";

interface Page {
  items: Analysis[];
  next_cursor: string | null;
}

export function SourceBadge({ analysis }: { analysis: Analysis }) {
  const source = analysis.source;
  if (source.kind === "ticket") {
    const label = `${source.platform === "zendesk" ? "Zendesk" : "Freshdesk"} #${source.ticket_id}`;
    return source.ticket_url ? (
      <a href={source.ticket_url} target="_blank" rel="noreferrer noopener" className="font-mono text-xs underline decoration-signal underline-offset-2 hover:text-signal">
        {label} ↗
      </a>
    ) : (
      <Tag tone="ink">{label}</Tag>
    );
  }
  return <Tag>{source.kind === "cli" ? "CLI" : "Upload"}</Tag>;
}

const PHONE_HIDDEN = new Set(["Source", "Requests", "Analysed", "Expires"]);
const STATUS_TONE = { done: "ok", failed: "bad", queued: "muted", running: "warn" } as const;

export function HistoryPage() {
  const [q, setQ] = useState("");
  const query = useInfiniteQuery({
    queryKey: ["analyses", q],
    queryFn: ({ pageParam }) => api<Page>("/v1/analyses", { query: { cursor: pageParam, q, limit: 25 } }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div>
      <PageHeader
        eyebrow="Case files"
        title="History"
        description="Every analysis in this organisation, newest first. Files and results are deleted automatically when they expire."
        action={<Input className="w-64" type="search" aria-label="Search by file name" placeholder="Search file names" value={q} onChange={(e) => setQ(e.target.value)} />}
      />
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : items.length === 0 ? (
        q ? (
          <EmptyState title="No matching files" action={<Button size="sm" onClick={() => setQ("")}>Clear search</Button>}>
            No file name contains “{q}”.
          </EmptyState>
        ) : (
          <EmptyState title="No analyses yet" action={<Link to="/" className="text-sm font-medium underline decoration-signal decoration-2 underline-offset-2">Analyse a file</Link>}>
            Upload a HAR file, or tag a ticket in a connected helpdesk.
          </EmptyState>
        )
      ) : (
        <div className="overflow-x-auto">
          <table className="min-w-full text-sm">
            <thead className="text-left">
              <tr className="border-b border-rule-2">
                {["File", "Source", "Status", "Likely cause", "Requests", "Analysed", "Expires"].map((h) => (
                  <th key={h} className={`eyebrow px-3 py-2.5 font-semibold whitespace-nowrap ${PHONE_HIDDEN.has(h) ? "max-md:hidden" : ""}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id} className="border-b border-rule align-top hover:bg-card">
                  <td className="max-w-[16rem] px-3 py-3">
                    <Link to={`/analyses/${a.id}`} className="block truncate font-medium text-ink hover:text-signal hover:underline" title={a.filename ?? undefined}>
                      {a.filename ?? "file.har"}
                    </Link>
                    <div className="font-mono text-xs text-ink-3">{bytes(a.original_size_bytes)}</div>
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap max-md:hidden">
                    <SourceBadge analysis={a} />
                  </td>
                  <td className="px-3 py-3">
                    <Tag tone={STATUS_TONE[a.status]}>{a.status}</Tag>
                  </td>
                  <td className="max-w-md px-3 py-3 text-ink-2">
                    <span className="line-clamp-2">{a.lead ? <Redacted text={a.lead} /> : (a.status === "done" ? <span className="text-ink-3">No failures found</span> : "—")}</span>
                  </td>
                  <td className="px-3 py-3 font-mono tabular-nums max-md:hidden">{a.entry_count}</td>
                  <td className="px-3 py-3 whitespace-nowrap text-ink-2 max-md:hidden" title={dateTime(a.finished_at ?? a.created_at)}>
                    {relative(a.finished_at ?? a.created_at)}
                  </td>
                  <td className="px-3 py-3 whitespace-nowrap text-ink-3 max-md:hidden" title={dateTime(a.expires_at)}>
                    {relative(a.expires_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {query.hasNextPage && (
            <div className="p-4 text-center">
              <Button size="sm" busy={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>
                Load more
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
