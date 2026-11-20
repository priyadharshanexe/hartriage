import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type FormEvent, useCallback, useState } from "react";
import { Button, Card, ConfirmButton, CopyButton, EmptyState, ErrorState, Field, Input, LoadingState, Notice, PageHeader, Select, Tag } from "../components/ui";
import { DrawCheck } from "../components/fx";
import { useToast } from "../components/Toasts";
import { api, fieldErrors } from "../lib/api";
import { dateTime, relative } from "../lib/format";
import type { Connection } from "../lib/types";

type Platform = "zendesk" | "freshdesk";

export function ConnectionsPage() {
  const queryClient = useQueryClient();
  const list = useQuery({ queryKey: ["connections"], queryFn: () => api<{ items: Connection[] }>("/v1/connections") });
  const [adding, setAdding] = useState(false);
  const [secret, setSecret] = useState<{ id: string; value: string } | null>(null);
  const [created, setCreated] = useState<string | null>(null);
  const clearCreated = useCallback(() => setCreated(null), []);

  const toast = useToast();
  const remove = useMutation({
    mutationFn: (id: string) => api<void>(`/v1/connections/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      toast("Helpdesk disconnected.");
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
    onError: () => toast("Could not disconnect.", "bad"),
  });

  return (
    <div className="max-w-4xl space-y-6">
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
            if (created) setCreated(`Connected to ${created.subdomain}.${created.platform}.com${created.account ? ` as ${created.account}` : ""}.`);
            void queryClient.invalidateQueries({ queryKey: ["connections"] });
          }}
        />
      )}
      {created && <Notice onDone={clearCreated}>{created}</Notice>}
      {remove.isError && <ErrorState error={remove.error} />}
      {list.isPending ? (
        <LoadingState />
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} />
      ) : list.data.items.length === 0 && !adding ? (
        <EmptyState title="No helpdesk connected">Add Zendesk or Freshdesk to analyse HAR files straight from tickets.</EmptyState>
      ) : (
        list.data.items.map((c) => (
          <ConnectionCard
            key={c.id}
            connection={c}
            secret={secret?.id === c.id ? secret.value : null}
            onSecret={(value) => setSecret({ id: c.id, value })}
            onDelete={() => remove.mutate(c.id)}
          />
        ))
      )}
    </div>
  );
}

function ConnectionCard({ connection: c, secret, onSecret, onDelete }: { connection: Connection; secret: string | null; onSecret: (s: string) => void; onDelete: () => void }) {
  const queryClient = useQueryClient();
  const [test, setTest] = useState<{ ok: boolean; text: string } | null>(null);
  const [testing, setTesting] = useState(false);
  const toast = useToast();
  const toggle = useMutation({
    mutationFn: (value: boolean) => api<Connection>(`/v1/connections/${c.id}`, { method: "PATCH", body: { replace_attachments: value } }),
    onSuccess: (_, value) => {
      toast(value ? "Originals will be replaced with the redacted copy." : "Originals will be left as they are.");
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
  });
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Tag tone="ink">{c.platform === "zendesk" ? "Zendesk" : "Freshdesk"}</Tag>
          <span className="font-mono text-sm tracking-normal text-ink normal-case">{c.subdomain}.{c.platform}.com</span>
        </span>
      }
      action={
        <div className="flex gap-2">
          <Button size="sm" busy={testing} onClick={async () => {
            setTesting(true);
            setTest(null);
            try {
              const result = await api<{ ok: boolean; account?: string; error?: string }>(`/v1/connections/${c.id}/test`, { method: "POST" });
              setTest(result.ok ? { ok: true, text: `Connected as ${result.account}` } : { ok: false, text: `Failed: ${result.error}` });
              toast(result.ok ? `Connection works: ${result.account}` : "The helpdesk refused the credentials.", result.ok ? "ok" : "bad");
            } catch (e) {
              setTest({ ok: false, text: e instanceof Error ? e.message : "The test failed." });
            } finally {
              setTesting(false);
            }
          }}>
            Test
          </Button>
          <ConfirmButton label="Disconnect" question="Delete this connection and its analyses?" confirmLabel="Disconnect" onConfirm={onDelete} />
        </div>
      }
    >
      {test && (
        <p role="status" className={`animate-slide-down mb-4 flex items-center gap-2 rounded-[6px] px-3 py-2 text-sm ${test.ok ? "bg-ok/10" : "bg-critical/10"}`}>
          {test.ok && <DrawCheck className="text-ok" />}
          {test.text}
        </p>
      )}
      {c.needs_signing_secret && <SigningSecretForm connection={c} />}
      {secret && (
        <div className="animate-slide-down mb-4 rounded-[6px] bg-medium/15 p-3 text-sm" role="alert">
          <p className="font-semibold">Webhook secret, shown once</p>
          <p className="mt-1">Add it as the <code className="font-mono">{c.secret_header}</code> header in the Freshdesk automation.</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <code className="bg-card px-2 py-1 font-mono text-xs [overflow-wrap:anywhere]">{secret}</code>
            <CopyButton getText={() => secret} />
          </div>
        </div>
      )}
      <dl className="grid gap-x-4 gap-y-3 text-sm md:grid-cols-[10rem_1fr]">
        <dt className="eyebrow pt-1.5">Webhook URL</dt>
        <dd className="flex flex-wrap items-center gap-2">
          <code className="bg-paper-2 px-2 py-1 font-mono text-xs [overflow-wrap:anywhere]">{c.webhook_url}</code>
          <CopyButton size="sm" getText={() => c.webhook_url} />
        </dd>
        <dt className="eyebrow pt-0.5">Last webhook</dt>
        <dd>
          {c.last_webhook_at ? (
            <span title={dateTime(c.last_webhook_at)} className="inline-flex flex-wrap items-center gap-2">
              {/* Heartbeat: green and beating while webhooks or polls succeed, red when the last one failed. */}
              <span className={`heartbeat ${/error|rejected/.test(c.last_webhook_status ?? "") ? "heartbeat-bad" : ""}`} aria-hidden="true" />
              {relative(c.last_webhook_at)} · <span className="font-mono text-xs">{c.last_webhook_status}</span>
            </span>
          ) : (
            <span className="text-ink-3">None received yet</span>
          )}
        </dd>
        <dt className="eyebrow pt-0.5">Original attachment</dt>
        <dd>
          <label className="flex items-start gap-2">
            <input type="checkbox" checked={c.replace_attachments} onChange={(e) => toggle.mutate(e.target.checked)} className="mt-1 accent-ink" />
            <span>
              Replace the customer's original HAR with the redacted copy after analysis.
              <span className="block text-xs text-ink-3">The original still holds live session tokens. Zendesk redacts it; Freshdesk deletes it.</span>
            </span>
          </label>
        </dd>
      </dl>
      <details className="mt-5 border-t border-rule pt-3">
        <summary className="eyebrow cursor-pointer text-ink hover:text-signal">Setup steps</summary>
        <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm text-ink-2 marker:font-mono marker:text-ink-3">
          {c.setup_steps.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ol>
        {c.platform === "freshdesk" && (
          <Button size="sm" className="mt-3" onClick={async () => {
            const rotated = await api<Connection>(`/v1/connections/${c.id}/rotate-secret`, { method: "POST" });
            if (rotated.webhook_secret) onSecret(rotated.webhook_secret);
            toast("New webhook secret generated. Update the Freshdesk rule.", "info");
          }}>
            Generate a new webhook secret
          </Button>
        )}
      </details>
    </Card>
  );
}

type ZendeskAuth = "oauth_client" | "api_token";

function NewConnection({ onDone }: { onDone: (created: Connection | null) => void }) {
  const [platform, setPlatform] = useState<Platform>("zendesk");
  // New Zendesk accounts can no longer create API tokens, so OAuth comes first.
  const [zendeskAuth, setZendeskAuth] = useState<ZendeskAuth>("oauth_client");
  const [form, setForm] = useState({
    subdomain: "",
    email: "",
    api_token: "",
    oauth_client_id: "",
    oauth_client_secret: "",
    api_key: "",
    signing_secret: "",
  });
  const create = useMutation({
    mutationFn: () =>
      api<Connection>("/v1/connections", {
        method: "POST",
        body:
          platform === "zendesk"
            ? {
                platform,
                subdomain: form.subdomain,
                ...(zendeskAuth === "oauth_client"
                  ? { oauth_client_id: form.oauth_client_id, oauth_client_secret: form.oauth_client_secret }
                  : { email: form.email, api_token: form.api_token }),
                signing_secret: form.signing_secret || undefined,
              }
            : { platform, subdomain: form.subdomain, api_key: form.api_key },
      }),
    onSuccess: (created) => onDone(created),
  });
  const errors = fieldErrors(create.error);
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm({ ...form, [key]: e.target.value });
    if (create.isError) create.reset();
  };
  return (
    <Card title="New connection">
      <form className="grid gap-4 md:grid-cols-2" onSubmit={(e: FormEvent) => { e.preventDefault(); create.mutate(); }}>
        <Field label="Helpdesk">
          {(p) => (
            <Select {...p} value={platform} onChange={(e) => { setPlatform(e.target.value as Platform); create.reset(); }}>
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
            <Field label="Sign in with">
              {(p) => (
                <Select {...p} value={zendeskAuth} onChange={(e) => { setZendeskAuth(e.target.value as ZendeskAuth); create.reset(); }}>
                  <option value="oauth_client">OAuth client (recommended)</option>
                  <option value="api_token">Agent email and API token</option>
                </Select>
              )}
            </Field>
            <div className="hidden md:block" />
            {zendeskAuth === "oauth_client" ? (
              <>
                <Field label="OAuth client unique identifier" hint="Admin Center → Apps and integrations → APIs → OAuth clients; client kind Confidential">
                  {(p) => <Input {...p} required value={form.oauth_client_id} onChange={set("oauth_client_id")} />}
                </Field>
                <Field label="OAuth client secret" hint="Shown once when you create the client">
                  {(p) => <Input {...p} type="password" required value={form.oauth_client_secret} onChange={set("oauth_client_secret")} />}
                </Field>
              </>
            ) : (
              <>
                <Field label="Agent email">{(p) => <Input {...p} type="email" required value={form.email} onChange={set("email")} />}</Field>
                <Field label="API token" hint="Zendesk stops accepting API tokens on 30 April 2027; new accounts cannot create them">
                  {(p) => <Input {...p} type="password" required value={form.api_token} onChange={set("api_token")} />}
                </Field>
              </>
            )}
            <Field label="Webhook signing secret (optional now)" hint="The webhook needs this connection's URL first. Add the secret afterwards on the connection.">
              {(p) => <Input {...p} type="password" value={form.signing_secret} onChange={set("signing_secret")} />}
            </Field>
          </>
        ) : (
          <Field label="API key" hint="Profile settings → View API key">
            {(p) => <Input {...p} type="password" required value={form.api_key} onChange={set("api_key")} />}
          </Field>
        )}
        <div className="md:col-span-2">
          {create.isError && Object.keys(errors).length === 0 && <div className="mb-3"><ErrorState error={create.error} /></div>}
          <p className="mb-3 text-xs text-ink-3">The credentials are checked against the helpdesk, then stored encrypted. They are never shown again.</p>
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

/** Zendesk shows the signing secret only after the webhook exists, so it is added here. */
function SigningSecretForm({ connection }: { connection: Connection }) {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const save = useMutation({
    mutationFn: () => api<Connection>(`/v1/connections/${connection.id}`, { method: "PATCH", body: { signing_secret: value } }),
    onSuccess: () => {
      setValue("");
      void queryClient.invalidateQueries({ queryKey: ["connections"] });
    },
  });
  return (
    <form
      className="animate-slide-down mb-4 rounded-[6px] bg-medium/15 p-3 text-sm"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <p className="font-semibold">Add the webhook signing secret</p>
      <p className="mt-1">Until it is added, webhooks from Zendesk are refused. Create the webhook with the URL below, reveal its signing secret, and paste it here.</p>
      <div className="mt-2 flex flex-wrap items-center gap-2">
        <Input className="w-80 max-w-full" type="password" aria-label="Webhook signing secret" required value={value} onChange={(e) => { setValue(e.target.value); save.reset(); }} />
        <Button type="submit" size="sm" variant="primary" busy={save.isPending}>
          Save secret
        </Button>
      </div>
      {save.isError && <div className="mt-2"><ErrorState error={save.error} /></div>}
    </form>
  );
}
