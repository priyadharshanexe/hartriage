import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { Badge, Button, Card, CopyButton, EmptyState, ErrorState, Field, Input, LoadingState, PageHeader, Select } from "../components/ui";
import { api, fieldErrors } from "../lib/api";
import { dateTime, relative } from "../lib/format";
import type { Connection } from "../lib/types";

type Platform = "zendesk" | "freshdesk";

export function ConnectionsPage() {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: ["connections"], queryFn: () => api<{ items: Connection[] }>("/v1/connections") });
  const [adding, setAdding] = useState(false);
  const [secret, setSecret] = useState<{ id: string; value: string } | null>(null);

  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/v1/connections/${id}`, { method: "DELETE" }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["connections"] }),
  });

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader
        title="Helpdesk connections"
        description="Connect Zendesk or Freshdesk. Agents tag a ticket that has a HAR attachment, and the analysis comes back as a private note."
        action={!adding && <Button variant="primary" onClick={() => setAdding(true)}>Add a connection</Button>}
      />
      {adding && (
        <NewConnection
          onDone={(created) => {
            setAdding(false);
            if (created?.webhook_secret) setSecret({ id: created.id, value: created.webhook_secret });
            void queryClient.invalidateQueries({ queryKey: ["connections"] });
          }}
        />
      )}
      {list.isPending ? (
        <LoadingState />
      ) : list.isError ? (
        <ErrorState error={list.error} />
      ) : list.data.items.length === 0 && !adding ? (
        <EmptyState title="No helpdesk connected">Add Zendesk or Freshdesk to analyse HAR files straight from tickets.</EmptyState>
      ) : (
        list.data.items.map((c) => (
          <ConnectionCard
            key={c.id}
            connection={c}
            secret={secret?.id === c.id ? secret.value : null}
            onSecret={(value) => setSecret({ id: c.id, value })}
            onDelete={() => {
              if (window.confirm(`Disconnect ${c.subdomain}? Its analyses and stored files are deleted too.`)) remove.mutate(c.id);
            }}
          />
        ))
      )}
    </div>
  );
}

function ConnectionCard({ connection: c, secret, onSecret, onDelete }: { connection: Connection; secret: string | null; onSecret: (s: string) => void; onDelete: () => void }) {
  const queryClient = useQueryClient();
  const [test, setTest] = useState<string | null>(null);
  const toggle = useMutation({
    mutationFn: (value: boolean) => api<Connection>(`/v1/connections/${c.id}`, { method: "PATCH", body: { replace_attachments: value } }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["connections"] }),
  });
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Badge tone="blue">{c.platform === "zendesk" ? "Zendesk" : "Freshdesk"}</Badge>
          {c.subdomain}.{c.platform}.com
        </span>
      }
      action={
        <div className="flex gap-2">
          <Button size="sm" onClick={async () => {
            const result = await api<{ ok: boolean; account?: string; error?: string }>(`/v1/connections/${c.id}/test`, { method: "POST" });
            setTest(result.ok ? `Connected as ${result.account}` : `Failed: ${result.error}`);
          }}>
            Test
          </Button>
          <Button size="sm" variant="danger" onClick={onDelete}>
            Disconnect
          </Button>
        </div>
      }
    >
      {test && <p className="mb-3 text-sm text-slate-700">{test}</p>}
      {secret && (
        <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm" role="alert">
          <p className="font-medium text-amber-900">Webhook secret, shown once</p>
          <p className="mt-1 text-amber-900">Add it as the <code>{c.secret_header}</code> header in the Freshdesk automation.</p>
          <div className="mt-2 flex items-center gap-2">
            <code className="break-all rounded bg-white px-2 py-1 font-mono text-xs">{secret}</code>
            <CopyButton getText={() => secret} />
          </div>
        </div>
      )}
      <dl className="grid gap-3 text-sm md:grid-cols-[10rem_1fr]">
        <dt className="text-slate-500">Webhook URL</dt>
        <dd className="flex flex-wrap items-center gap-2">
          <code className="break-all rounded bg-slate-50 px-2 py-1 font-mono text-xs">{c.webhook_url}</code>
          <CopyButton getText={() => c.webhook_url} />
        </dd>
        <dt className="text-slate-500">Last webhook</dt>
        <dd>
          {c.last_webhook_at ? (
            <span title={dateTime(c.last_webhook_at)}>
              {relative(c.last_webhook_at)} — {c.last_webhook_status}
            </span>
          ) : (
            "None received yet"
          )}
        </dd>
        <dt className="text-slate-500">Original attachment</dt>
        <dd>
          <label className="flex items-start gap-2">
            <input type="checkbox" checked={c.replace_attachments} onChange={(e) => toggle.mutate(e.target.checked)} className="mt-1" />
            <span>
              Replace the customer's original HAR with the redacted copy after analysis.
              <span className="block text-xs text-slate-500">The original still holds live session tokens. Zendesk redacts it; Freshdesk deletes it.</span>
            </span>
          </label>
        </dd>
      </dl>
      <details className="mt-4">
        <summary className="cursor-pointer text-sm font-medium text-brand-700">Setup steps</summary>
        <ol className="mt-2 list-decimal space-y-2 pl-5 text-sm text-slate-700">
          {c.setup_steps.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
        {c.platform === "freshdesk" && (
          <Button size="sm" className="mt-3" onClick={async () => {
            const rotated = await api<Connection>(`/v1/connections/${c.id}/rotate-secret`, { method: "POST" });
            if (rotated.webhook_secret) onSecret(rotated.webhook_secret);
          }}>
            Generate a new webhook secret
          </Button>
        )}
      </details>
    </Card>
  );
}

function NewConnection({ onDone }: { onDone: (created: Connection | null) => void }) {
  const [platform, setPlatform] = useState<Platform>("zendesk");
  const [form, setForm] = useState({ subdomain: "", email: "", api_token: "", api_key: "", signing_secret: "" });
  const create = useMutation({
    mutationFn: () =>
      api<Connection>("/v1/connections", {
        method: "POST",
        body: platform === "zendesk"
          ? { platform, subdomain: form.subdomain, email: form.email, api_token: form.api_token, signing_secret: form.signing_secret }
          : { platform, subdomain: form.subdomain, api_key: form.api_key },
      }),
    onSuccess: (created) => onDone(created),
  });
  const errors = fieldErrors(create.error);
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value });
  return (
    <Card title="New connection">
      <form className="grid gap-4 md:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
        <Field label="Helpdesk">
          {(p) => (
            <Select {...p} value={platform} onChange={(e) => setPlatform(e.target.value as Platform)}>
              <option value="zendesk">Zendesk</option>
              <option value="freshdesk">Freshdesk</option>
            </Select>
          )}
        </Field>
        <Field label="Subdomain" hint={`acme for acme.${platform}.com`} error={errors.subdomain}>
          {(p) => <Input {...p} required value={form.subdomain} onChange={set("subdomain")} />}
        </Field>
        {platform === "zendesk" ? (
          <>
            <Field label="Agent email">{(p) => <Input {...p} type="email" required value={form.email} onChange={set("email")} />}</Field>
            <Field label="API token" hint="Admin Center → Apps and integrations → APIs → Zendesk API">
              {(p) => <Input {...p} type="password" required value={form.api_token} onChange={set("api_token")} />}
            </Field>
            <Field label="Webhook signing secret" hint="Shown on the webhook's page in Zendesk after you create it">
              {(p) => <Input {...p} type="password" required value={form.signing_secret} onChange={set("signing_secret")} />}
            </Field>
          </>
        ) : (
          <Field label="API key" hint="Profile settings → View API key">
            {(p) => <Input {...p} type="password" required value={form.api_key} onChange={set("api_key")} />}
          </Field>
        )}
        <div className="md:col-span-2">
          {create.isError && Object.keys(errors).length === 0 && <ErrorState error={create.error} />}
          <p className="mb-3 text-xs text-slate-500">The credentials are checked against the helpdesk, then stored encrypted. They are never shown again.</p>
          <div className="flex gap-2">
            <Button type="submit" variant="primary" busy={create.isPending}>
              Connect
            </Button>
            <Button onClick={() => onDone(null)}>Cancel</Button>
          </div>
        </div>
      </form>
    </Card>
  );
}
