import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Button, Card, ConfirmButton, CopyButton, ErrorState, Field, Input, LoadingState, PageHeader, Select, Tag } from "../components/ui";
import { api } from "../lib/api";
import { relative } from "../lib/format";
import type { Invitation, Member, Role } from "../lib/types";

const ROLE_HELP: Record<Role, string> = {
  admin: "Everything, including connections, the team and deleting analyses.",
  agent: "Upload files, read analyses, download redacted copies.",
  viewer: "Read analyses only.",
};

export function TeamPage() {
  const queryClient = useQueryClient();
  const team = useQuery({ queryKey: ["members"], queryFn: () => api<{ members: Member[]; invitations: Invitation[] }>("/v1/members") });
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("agent");
  const [link, setLink] = useState<string | null>(null);
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["members"] });

  const invite = useMutation({
    mutationFn: () => api<Invitation>("/v1/invitations", { method: "POST", body: { email, role } }),
    onSuccess: (inv) => {
      setLink(inv.invite_url ?? null);
      setEmail("");
      refresh();
    },
  });
  const change = useMutation({
    mutationFn: ({ userId, next }: { userId: string; next: Role }) => api(`/v1/members/${userId}`, { method: "PATCH", body: { role: next } }),
    onSuccess: refresh,
  });
  const remove = useMutation({ mutationFn: (userId: string) => api(`/v1/members/${userId}`, { method: "DELETE" }), onSuccess: refresh });

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader eyebrow="Administration" title="Team" description="Invite people by link and choose what they can do." />
      <Card title="Invite someone">
        <form className="flex flex-wrap items-end gap-3" onSubmit={(e: FormEvent) => { e.preventDefault(); invite.mutate(); }}>
          <div className="min-w-[16rem] flex-1">
            <Field label="Email">{(p) => <Input {...p} type="email" required value={email} onChange={(e) => { setEmail(e.target.value); if (invite.isError) invite.reset(); }} />}</Field>
          </div>
          <Field label="Role">
            {(p) => (
              <Select {...p} className="w-36" value={role} onChange={(e) => setRole(e.target.value as Role)}>
                <option value="agent">Agent</option>
                <option value="viewer">Viewer</option>
                <option value="admin">Admin</option>
              </Select>
            )}
          </Field>
          <Button type="submit" variant="primary" busy={invite.isPending}>
            Create invitation link
          </Button>
        </form>
        <p className="mt-2 text-xs text-ink-3">{ROLE_HELP[role]}</p>
        {invite.isError && <div className="mt-3"><ErrorState error={invite.error} /></div>}
        {link && (
          <div className="mt-4 border-l-4 border-ok bg-ok/[0.08] p-3 text-sm">
            <p className="font-medium">Send this link. It is shown once and is valid for 7 days.</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <code className="bg-card px-2 py-1 font-mono text-xs [overflow-wrap:anywhere]">{link}</code>
              <CopyButton size="sm" getText={() => link} />
            </div>
          </div>
        )}
      </Card>
      {team.isPending ? (
        <LoadingState />
      ) : team.isError ? (
        <ErrorState error={team.error} onRetry={() => void team.refetch()} />
      ) : (
        <Card title="Members">
          {(change.isError || remove.isError) && <div className="mb-3"><ErrorState error={change.error ?? remove.error} /></div>}
          <ul className="divide-y divide-rule">
            {team.data.members.map((m) => (
              <li key={m.user_id} className="flex flex-wrap items-center gap-3 py-3 text-sm">
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{m.name || m.email}</span> {m.you && <Tag tone="ink">you</Tag>}
                  <span className="block font-mono text-xs text-ink-3">{m.email} · joined {relative(m.joined_at)}</span>
                </span>
                <Select
                  aria-label={`Role for ${m.email}`}
                  className="w-36"
                  value={m.role}
                  disabled={m.you || change.isPending}
                  title={m.you ? "You cannot change your own role. Ask another admin." : undefined}
                  onChange={(e) => { remove.reset(); change.mutate({ userId: m.user_id, next: e.target.value as Role }); }}
                >
                  <option value="admin">Admin</option>
                  <option value="agent">Agent</option>
                  <option value="viewer">Viewer</option>
                </Select>
                {!m.you && <ConfirmButton label="Remove" question={`Remove ${m.email}?`} confirmLabel="Remove" onConfirm={() => { change.reset(); remove.mutate(m.user_id); }} />}
              </li>
            ))}
            {team.data.invitations.map((i) => (
              <li key={i.id} className="flex flex-wrap items-center gap-3 py-3 text-sm text-ink-3">
                <span className="min-w-0 flex-1">
                  <span className="font-mono text-ink-2">{i.email}</span> <Tag>pending</Tag>
                  <span className="block text-xs">invited as {i.role} · expires {relative(i.expires_at)}</span>
                </span>
                <Button size="sm" variant="ghost" onClick={async () => { await api(`/v1/invitations/${i.id}`, { method: "DELETE" }); refresh(); }}>
                  Cancel
                </Button>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
