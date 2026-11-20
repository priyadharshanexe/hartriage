import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link } from "react-router-dom";
import { EmptyState, ErrorState, LoadingState, PageHeader } from "../components/ui";
import { api } from "../lib/api";
import { dateTime } from "../lib/format";
import type { AuditEntry } from "../lib/types";

const ACTIONS: Record<string, string> = {
  "analysis.uploaded": "uploaded a file",
  "analysis.viewed": "viewed an analysis",
  "analysis.exported": "exported a summary",
  "analysis.downloaded": "downloaded a redacted file",
  "analysis.rerun": "re-ran an analysis",
  "analysis.from_ticket": "analysed a ticket attachment",
  "artifact.expired": "retention deleted a file",
  "artifact.deleted": "deleted an analysis",
  "attachment.replaced": "replaced a ticket attachment with its redacted copy",
  "connection.created": "connected a helpdesk",
  "connection.updated": "changed a connection",
  "connection.deleted": "disconnected a helpdesk",
  "connection.secret_rotated": "rotated a webhook secret",
  "member.invited": "invited someone",
  "member.joined": "joined",
  "member.role_changed": "changed a role",
  "member.removed": "removed someone",
  "org.created": "created the organisation",
};

export function AuditPage() {
  const log = useQuery({ queryKey: ["audit"], queryFn: () => api<{ items: AuditEntry[] }>("/v1/audit", { query: { limit: 200 } }), refetchInterval: 15000 });
  const seen = useRef<Set<string> | null>(null);
  const keyOf = (a: AuditEntry) => `${a.at}|${a.action}|${a.target_id ?? ""}|${a.actor ?? ""}`;
  const fresh = new Set<string>();
  if (log.data) {
    if (seen.current) for (const a of log.data.items) if (!seen.current.has(keyOf(a))) fresh.add(keyOf(a));
  }
  useEffect(() => {
    if (log.data) seen.current = new Set(log.data.items.map(keyOf));
  }, [log.data]);
  return (
    <div className="max-w-5xl">
      <PageHeader title="Audit log" description="Who viewed, exported, downloaded or changed what, and when. Newest first." />
      {log.isPending ? (
        <LoadingState />
      ) : log.isError ? (
        <ErrorState error={log.error} onRetry={() => void log.refetch()} />
      ) : log.data.items.length === 0 ? (
        <EmptyState title="Nothing yet" />
      ) : (
        <ol className="text-sm">
          {log.data.items.map((a, i) => (
            <li key={keyOf(a) + i} style={{ animationDelay: `${Math.min(i, 15) * 25}ms` }} className={`animate-rise ${fresh.has(keyOf(a)) ? "flash-new" : ""} grid gap-x-4 gap-y-0.5 border-b border-rule py-2.5 sm:grid-cols-[11rem_minmax(0,1fr)]`}>
              <span className="font-mono text-xs text-ink-3 sm:pt-0.5">{dateTime(a.at)}</span>
              <span className="min-w-0">
                <span className="font-medium">{a.actor ?? "HAR Triage"}</span> <span className="text-ink-2">{ACTIONS[a.action] ?? a.action}</span>
                {a.target_type === "analysis" && a.target_id && (
                  <>
                    {" "}
                    <Link className="text-xs underline decoration-signal underline-offset-2 hover:text-signal" to={`/analyses/${a.target_id}`}>
                      open
                    </Link>
                  </>
                )}
                {Object.keys(a.details).length > 0 && (
                  <span className="block font-mono text-xs break-words text-ink-4">
                    {Object.entries(a.details)
                      .map(([k, v]) => `${k}: ${String(v)}`)
                      .join(" · ")}
                  </span>
                )}
              </span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
