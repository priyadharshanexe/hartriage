import { useQuery } from "@tanstack/react-query";
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
  const log = useQuery({ queryKey: ["audit"], queryFn: () => api<{ items: AuditEntry[] }>("/v1/audit", { query: { limit: 200 } }) });
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Audit log" description="Who viewed, exported, downloaded or changed what, and when." />
      {log.isPending ? (
        <LoadingState />
      ) : log.isError ? (
        <ErrorState error={log.error} />
      ) : log.data.items.length === 0 ? (
        <EmptyState title="Nothing yet" />
      ) : (
        <ol className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white text-sm">
          {log.data.items.map((a, i) => (
            <li key={`${a.at}-${i}`} className="flex flex-wrap gap-x-3 px-4 py-2">
              <span className="w-44 shrink-0 text-slate-500">{dateTime(a.at)}</span>
              <span className="font-medium">{a.actor ?? "HAR Triage"}</span>
              <span className="text-slate-700">{ACTIONS[a.action] ?? a.action}</span>
              {a.target_type === "analysis" && a.target_id && (
                <Link className="text-brand-700 underline" to={`/analyses/${a.target_id}`}>
                  open
                </Link>
              )}
              {Object.keys(a.details).length > 0 && <span className="text-xs text-slate-400">{Object.entries(a.details).map(([k, v]) => `${k}: ${String(v)}`).join(", ")}</span>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
