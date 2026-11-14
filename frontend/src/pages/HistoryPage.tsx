import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, EmptyState, ErrorState, Input, LoadingState, PageHeader } from "../components/ui";
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
      <a href={source.ticket_url} target="_blank" rel="noreferrer noopener" className="text-brand-700 underline">
        {label}
      </a>
    ) : (
      <Badge tone="blue">{label}</Badge>
    );
  }
  return <Badge>{source.kind === "cli" ? "CLI" : "Upload"}</Badge>;
}

const STATUS_TONE = { done: "green", failed: "red", queued: "slate", running: "blue" } as const;

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
        title="History"
        description="Every analysis in this organisation, newest first. Files and results are deleted automatically when they expire."
        action={<Input aria-label="Search by file name" placeholder="Search file names" value={q} onChange={(e) => setQ(e.target.value)} />}
      />
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : items.length === 0 ? (
        <EmptyState title="No analyses yet" action={<Link to="/" className="text-sm font-medium text-brand-700">Analyse a file</Link>}>
          Upload a HAR file, or tag a ticket in a connected helpdesk.
        </EmptyState>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-2">File</th>
                <th className="px-4 py-2">Source</th>
                <th className="px-4 py-2">Status</th>
                <th className="px-4 py-2">Likely cause</th>
                <th className="px-4 py-2">Requests</th>
                <th className="px-4 py-2">Analysed</th>
                <th className="px-4 py-2">Expires</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((a) => (
                <tr key={a.id} className="hover:bg-slate-50">
                  <td className="max-w-[16rem] truncate px-4 py-2 font-medium">
                    <Link to={`/analyses/${a.id}`} className="text-brand-700 hover:underline">
                      {a.filename ?? "file.har"}
                    </Link>
                    <div className="text-xs font-normal text-slate-500">{bytes(a.original_size_bytes)}</div>
                  </td>
                  <td className="px-4 py-2">
                    <SourceBadge analysis={a} />
                  </td>
                  <td className="px-4 py-2">
                    <Badge tone={STATUS_TONE[a.status]}>{a.status}</Badge>
                  </td>
                  <td className="max-w-md px-4 py-2 text-slate-600">
                    <span className="line-clamp-2">{a.lead ?? (a.status === "done" ? "No failures found" : "—")}</span>
                  </td>
                  <td className="px-4 py-2 tabular-nums">{a.entry_count}</td>
                  <td className="whitespace-nowrap px-4 py-2 text-slate-600" title={dateTime(a.created_at)}>
                    {relative(a.created_at)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-2 text-slate-600" title={dateTime(a.expires_at)}>
                    {relative(a.expires_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {query.hasNextPage && (
            <div className="border-t border-slate-100 p-3 text-center">
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
