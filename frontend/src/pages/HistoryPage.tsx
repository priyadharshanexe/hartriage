import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { useToast } from "../components/Toasts";
import { Button, ConfirmButton, cx, EmptyState, ErrorState, Input, LoadingState, PageHeader, Redacted, Select, Tag } from "../components/ui";
import { api } from "../lib/api";
import { bytes, dateTime, relative } from "../lib/format";
import { caseTitle, useTransitionNavigate } from "../lib/transition";
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
  const go = useTransitionNavigate();
  return (
    <Link
      to={`/analyses/${a.id}`}
      // The file name morphs into the analysis page's header (View Transitions).
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        go(`/analyses/${a.id}`);
      }}
      style={caseTitle(a.id)}
      className="block font-mono text-sm font-medium break-words text-ink [overflow-wrap:anywhere] hover:text-signal hover:underline"
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

type Range = "" | "1" | "7" | "30";

async function downloadRedacted(a: Analysis) {
  const text = await api<string>(`/v1/analyses/${a.id}/redacted.har`, { text: true });
  const url = URL.createObjectURL(new Blob([text], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `${(a.filename ?? "file.har").replace(/\.[^.]+$/, "")}.redacted.har`;
  link.click();
  URL.revokeObjectURL(url);
}

/** Who may delete: agents their own uploads, admins anything (ticket files included). */
export function canDelete(a: Analysis, me: string | undefined, role: string | null): boolean {
  return role === "admin" || (role === "agent" && a.uploaded_by?.id === me && a.source.kind !== "ticket");
}

function FileActions({ analysis: a, onDeleted }: { analysis: Analysis; onDeleted: (a: Analysis) => void }) {
  const { session, role, canEdit } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  return (
    <div className="flex flex-wrap items-center gap-1">
      {canEdit && (
        <Button size="sm" variant="ghost" onClick={() => void downloadRedacted(a).then(() => toast("Redacted copy downloaded."), () => toast("The download failed.", "bad"))}>
          Download
        </Button>
      )}
      {canDelete(a, session?.user.id, role) && (
        <ConfirmButton
          label="Delete"
          question={`Delete ${a.filename ?? "this file"}? The redacted copy and its analysis are removed now.`}
          confirmLabel="Delete"
          busy={busy}
          onConfirm={async () => {
            setBusy(true);
            try {
              await api(`/v1/analyses/${a.id}`, { method: "DELETE" });
              onDeleted(a);
            } catch {
              toast("Could not delete the file.", "bad");
            } finally {
              setBusy(false);
            }
          }}
        />
      )}
    </div>
  );
}

export function HistoryPage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [q, setQ] = useState("");
  const [scope, setScope] = useState<"all" | "mine">("all");
  const [source, setSource] = useState("");
  const [status, setStatus] = useState("");
  const [range, setRange] = useState<Range>("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const since = range ? new Date(Date.now() - Number(range) * 86_400_000).toISOString() : undefined;
  const key = ["analyses", q, scope, source, status, range];
  const query = useInfiniteQuery({
    queryKey: key,
    queryFn: ({ pageParam }) =>
      api<Page>("/v1/analyses", {
        query: { cursor: pageParam, q, limit: 25, scope: isAdmin ? scope : undefined, source: source || undefined, status: status || undefined, since },
      }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];
  const filtered = Boolean(q || source || status || range || scope === "mine");

  function removed(gone: Analysis[]) {
    const ids = new Set(gone.map((a) => a.id));
    queryClient.setQueryData(key, (old: { pages: Page[]; pageParams: unknown[] } | undefined) =>
      old ? { ...old, pages: old.pages.map((p) => ({ ...p, items: p.items.filter((a) => !ids.has(a.id)) })) } : old,
    );
    setPicked((p) => new Set([...p].filter((id) => !ids.has(id))));
  }
  function onDeleted(a: Analysis) {
    toast(`Deleted ${a.filename ?? "the file"}.`);
    removed([a]);
  }
  async function bulkDelete() {
    setBulkBusy(true);
    try {
      const gone = items.filter((a) => picked.has(a.id));
      const result = await api<{ deleted: number }>("/v1/analyses/bulk-delete", { method: "POST", body: { ids: gone.map((a) => a.id) } });
      toast(`Deleted ${result.deleted} file${result.deleted === 1 ? "" : "s"}.`);
      removed(gone);
    } catch {
      toast("Could not delete those files.", "bad");
    } finally {
      setBulkBusy(false);
    }
  }
  const toggle = (id: string) =>
    setPicked((p) => {
      const next = new Set(p);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  const allPicked = items.length > 0 && items.every((a) => picked.has(a.id));
  // Deleted rows slide out and collapse.
  const exit = { opacity: 0, x: -40, transition: { duration: 0.25 } };

  return (
    <div>
      <PageHeader
        title="Files"
        description={
          isAdmin
            ? "Every file uploaded in this organisation, and every file from a helpdesk ticket. Only redacted copies are stored, and each is deleted automatically when it expires."
            : "The files you uploaded. Only redacted copies are stored, and each is deleted automatically when it expires."
        }
        action={<Input className="w-64" type="search" aria-label="Search by file name" placeholder="Search file names" value={q} onChange={(e) => setQ(e.target.value)} />}
      />
      <div className="mb-5 flex flex-wrap items-center gap-2">
        {isAdmin && (
          <div role="radiogroup" aria-label="Whose files" className="relative inline-flex rounded-full border border-rule bg-card p-0.5 text-sm">
            {(["all", "mine"] as const).map((v) => (
              <button key={v} type="button" role="radio" aria-checked={scope === v} onClick={() => setScope(v)} className={cx("relative h-8 rounded-full px-4", scope === v ? "font-bold text-ink" : "text-ink-3 hover:text-ink")}>
                {scope === v && <motion.span layoutId="scope-pill" className="absolute inset-0 rounded-full bg-raised" transition={{ type: "spring", stiffness: 500, damping: 38 }} />}
                <span className="relative">{v === "all" ? "All files" : "Mine"}</span>
              </button>
            ))}
          </div>
        )}
        <Select className="w-44" aria-label="Source" value={source} onChange={(e) => setSource(e.target.value)}>
          <option value="">Any source</option>
          <option value="upload">Uploads</option>
          <option value="ticket">Helpdesk tickets</option>
          <option value="cli">CLI</option>
        </Select>
        <Select className="w-36" aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Any status</option>
          <option value="done">Done</option>
          <option value="running">Running</option>
          <option value="queued">Queued</option>
          <option value="failed">Failed</option>
        </Select>
        <Select className="w-40" aria-label="Uploaded" value={range} onChange={(e) => setRange(e.target.value as Range)}>
          <option value="">Any time</option>
          <option value="1">Last 24 hours</option>
          <option value="7">Last 7 days</option>
          <option value="30">Last 30 days</option>
        </Select>
        <AnimatePresence>
          {isAdmin && picked.size > 0 && (
            <motion.div className="ml-auto" initial={{ opacity: 0, y: -6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }}>
              <ConfirmButton
                size="md"
                label={`Delete ${picked.size} selected`}
                question={`Delete ${picked.size} file${picked.size === 1 ? "" : "s"} and their analyses now?`}
                confirmLabel="Delete"
                busy={bulkBusy}
                onConfirm={() => void bulkDelete()}
              />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      {query.isPending ? (
        <LoadingState />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : items.length === 0 ? (
        filtered ? (
          <EmptyState
            title="No matching files"
            action={
              <Button
                size="sm"
                onClick={() => {
                  setQ("");
                  setSource("");
                  setStatus("");
                  setRange("");
                  setScope("all");
                }}
              >
                Clear filters
              </Button>
            }
          >
            Nothing matches these filters.
          </EmptyState>
        ) : (
          <EmptyState title="No files yet" action={<Link to="/" className="text-sm font-bold text-signal hover:underline">Analyse a file</Link>}>
            Upload a HAR file{isAdmin ? ", or tag a ticket in a connected helpdesk" : ""}.
          </EmptyState>
        )
      ) : (
        <div>
          {/* Wide screens: a fixed-layout table. Narrower screens: one card per file. */}
          <table className="hidden w-full table-fixed text-sm min-[1440px]:table">
            <colgroup>
              {isAdmin && <col className="w-10" />}
              <col className="w-52" />
              {isAdmin && <col className="w-36" />}
              <col className="w-28" />
              <col className="w-20" />
              <col />
              <col className="w-36" />
              <col className="w-40" />
            </colgroup>
            <thead className="text-left">
              <tr className="border-b border-rule-2">
                {isAdmin && (
                  <th className="px-3 py-2.5">
                    <input type="checkbox" aria-label="Select all" className="h-4 w-4 accent-[var(--primary)]" checked={allPicked} onChange={() => setPicked(allPicked ? new Set() : new Set(items.map((a) => a.id)))} />
                  </th>
                )}
                {["File", ...(isAdmin ? ["Uploaded by"] : []), "Source", "Status", "Likely cause", "When", ""].map((h, i) => (
                  <th key={`${h}-${i}`} className="colhead px-3 py-2.5 whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <AnimatePresence>
                {items.map((a, i) => (
                  <motion.tr
                    key={a.id}
                    layout
                    initial={{ opacity: 0, y: 12 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={exit}
                    transition={{ type: "spring", stiffness: 380, damping: 32, delay: Math.min(i, 12) * 0.03 }}
                    className={cx("border-b border-rule align-top transition-colors duration-150 hover:bg-card", picked.has(a.id) && "bg-signal-soft/60")}
                  >
                    {isAdmin && (
                      <td className="px-3 py-3">
                        <input type="checkbox" aria-label={`Select ${a.filename ?? "file"}`} className="h-4 w-4 accent-[var(--primary)]" checked={picked.has(a.id)} onChange={() => toggle(a.id)} />
                      </td>
                    )}
                    <td className="px-3 py-3">
                      <FileLink analysis={a} />
                      <div className="font-mono text-xs text-ink-3">
                        {bytes(a.original_size_bytes)} · {requests(a.entry_count)}
                      </div>
                    </td>
                    {isAdmin && (
                      <td className="truncate px-3 py-3 text-ink-2" title={a.uploaded_by?.email}>
                        {a.uploaded_by ? a.uploaded_by.name || a.uploaded_by.email : <span className="text-ink-4">helpdesk</span>}
                      </td>
                    )}
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
                    <td className="px-3 py-2">
                      <FileActions analysis={a} onDeleted={onDeleted} />
                    </td>
                  </motion.tr>
                ))}
              </AnimatePresence>
            </tbody>
          </table>
          <ul aria-label="Analyses" className="divide-y divide-rule border-y border-rule min-[1440px]:hidden">
            <AnimatePresence>
              {items.map((a, i) => (
                <motion.li
                  key={a.id}
                  layout
                  initial={{ opacity: 0, y: 14 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={exit}
                  transition={{ type: "spring", stiffness: 380, damping: 32, delay: Math.min(i, 12) * 0.03 }}
                  className="py-4"
                >
                  <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1">
                    <div className="flex min-w-0 flex-1 gap-3">
                      {isAdmin && <input type="checkbox" aria-label={`Select ${a.filename ?? "file"}`} className="mt-1 h-4 w-4 accent-[var(--primary)]" checked={picked.has(a.id)} onChange={() => toggle(a.id)} />}
                      <div className="min-w-0 flex-1">
                        <FileLink analysis={a} />
                        <div className="font-mono text-xs text-ink-3">{bytes(a.original_size_bytes)}</div>
                      </div>
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
                    {isAdmin && a.uploaded_by && <>by {a.uploaded_by.name || a.uploaded_by.email} · </>}
                    analysed <span title={dateTime(a.finished_at ?? a.created_at)}>{relative(a.finished_at ?? a.created_at)}</span>
                    {" · "}
                    {requests(a.entry_count)}
                    {" · "}
                    expires <span title={dateTime(a.expires_at)}>{relative(a.expires_at)}</span>
                  </p>
                  <div className="mt-2">
                    <FileActions analysis={a} onDeleted={onDeleted} />
                  </div>
                </motion.li>
              ))}
            </AnimatePresence>
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
