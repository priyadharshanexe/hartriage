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

const STATUS_TONE = { done: "ok", failed: "bad", queued: "muted", running: "warn" } as const;

function requests(n: number): string {
  return `${n.toLocaleString()} ${n === 1 ? "request" : "requests"}`;
}

function FileLink({ analysis: a }: { analysis: Analysis }) {
  return (
    <Link
      to={`/analyses/${a.id}`}
      className="block font-medium break-words text-ink [overflow-wrap:anywhere] hover:text-signal hover:underline"
    >
      {a.filename ?? "file.har"}
    </Link>
  );
}

/** The most useful thing on the page: wraps to three lines rather than being cut. */
function LikelyCause({ analysis: a }: { analysis: Analysis }) {
  if (!a.lead) {
    return a.status === "done" ? <span className="text-ink-3">No failures found</span> : <span>—</span>;
  }
  return (
    <p className="line-clamp-3" data-testid="likely-cause" title={a.lead}>
      <Redacted text={a.lead} />
    </p>
  );
}

function When({ analysis: a }: { analysis: Analysis }) {
  return (
    <>
      <div title={dateTime(a.finished_at ?? a.created_at)}>analysed {relative(a.finished_at ?? a.created_at)}</div>
      <div title={dateTime(a.expires_at)}>expires {relative(a.expires_at)}</div>
    </>
  );
}

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
        <div>
          {/* Wide screens: a fixed-layout table, so the likely cause wraps instead of
              stretching the table. Narrower screens: one card per analysis. */}
          <table className="hidden w-full table-fixed text-sm xl:table">
            <colgroup>
              <col className="w-56" />
              <col className="w-32" />
              <col className="w-24" />
              <col />
              <col className="w-40" />
            </colgroup>
            <thead className="text-left">
              <tr className="border-b border-rule-2">
                {["File", "Source", "Status", "Likely cause", "When"].map((h) => (
                  <th key={h} className="eyebrow px-3 py-2.5 font-semibold whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {items.map((a) => (
                <tr key={a.id} className="border-b border-rule align-top hover:bg-card">
                  <td className="px-3 py-3">
                    <FileLink analysis={a} />
                    <div className="font-mono text-xs text-ink-3">
                      {bytes(a.original_size_bytes)} · {requests(a.entry_count)}
                    </div>
                  </td>
                  <td className="px-3 py-3">
                    <SourceBadge analysis={a} />
                  </td>
                  <td className="px-3 py-3">
                    <Tag tone={STATUS_TONE[a.status]}>{a.status}</Tag>
                  </td>
                  <td className="px-3 py-3 text-ink-2">
                    <LikelyCause analysis={a} />
                  </td>
                  <td className="px-3 py-3 text-xs text-ink-3">
                    <When analysis={a} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul aria-label="Analyses" className="divide-y divide-rule border-y border-rule xl:hidden">
            {items.map((a) => (
              <li key={a.id} className="py-4">
                <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
                  <div className="min-w-0 flex-1">
                    <FileLink analysis={a} />
                    <div className="font-mono text-xs text-ink-3">{bytes(a.original_size_bytes)}</div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <SourceBadge analysis={a} />
                    <Tag tone={STATUS_TONE[a.status]}>{a.status}</Tag>
                  </div>
                </div>
                <div className="mt-2 text-sm text-ink-2">
                  <LikelyCause analysis={a} />
                </div>
                <p className="mt-2 text-xs text-ink-3">
                  analysed <span title={dateTime(a.finished_at ?? a.created_at)}>{relative(a.finished_at ?? a.created_at)}</span>
                  {" · "}
                  {requests(a.entry_count)}
                  {" · "}
                  expires <span title={dateTime(a.expires_at)}>{relative(a.expires_at)}</span>
                </p>
              </li>
            ))}
          </ul>
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
