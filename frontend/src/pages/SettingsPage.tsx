import { useQuery, useQueryClient } from "@tanstack/react-query";
import { motion } from "motion/react";
import { type FormEvent, useEffect, useState } from "react";
import { useToast } from "../components/Toasts";
import { Button, Card, cx, ErrorState, Field, Input, LoadingState, PageHeader } from "../components/ui";
import { api, fieldErrors } from "../lib/api";
import { bytes } from "../lib/format";

interface OrgSettings {
  retention_days: number;
  retention_choices: number[];
  max_file_mb: number | null;
  server_max_file_mb: number;
  effective_max_file_mb: number;
  storage_quota_mb: number | null;
  daily_uploads_per_member: number | null;
  storage_used_bytes: number;
  uploads_today: number;
}

interface Usage {
  storage_used_bytes: number;
  storage_quota_bytes: number | null;
  members: { user_id: string | null; name: string; email: string | null; bytes: number; files: number | null }[];
}

const optional = (v: string) => (v.trim() === "" ? null : Number(v));

function UsageBar({ used, quota }: { used: number; quota: number | null }) {
  const share = quota ? Math.min(1, used / quota) : 0;
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="font-mono text-ink">{bytes(used)}</span>
        <span className="text-ink-3">{quota ? `of ${bytes(quota)} (${Math.round(share * 100)}%)` : "no quota set"}</span>
      </div>
      <div className="mt-2 h-2.5 overflow-hidden rounded-full bg-raised" role="meter" aria-label="Storage used" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(share * 100)}>
        <motion.div
          className={cx("h-full rounded-full", share >= 0.9 ? "bg-critical" : share >= 0.7 ? "bg-medium" : "bg-signal")}
          initial={{ width: 0 }}
          animate={{ width: `${quota ? Math.max(share * 100, used ? 1 : 0) : 0}%` }}
          transition={{ type: "spring", stiffness: 120, damping: 22 }}
        />
      </div>
    </div>
  );
}

export function SettingsPage() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const settings = useQuery({ queryKey: ["org-settings"], queryFn: () => api<OrgSettings>("/v1/org/settings") });
  const usage = useQuery({ queryKey: ["org-usage"], queryFn: () => api<Usage>("/v1/org/usage") });
  const [form, setForm] = useState({ retention_days: 30, max_file_mb: "", storage_quota_mb: "", daily_uploads_per_member: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const s = settings.data;
  useEffect(() => {
    if (!s) return;
    setForm({
      retention_days: s.retention_days,
      max_file_mb: s.max_file_mb?.toString() ?? "",
      storage_quota_mb: s.storage_quota_mb?.toString() ?? "",
      daily_uploads_per_member: s.daily_uploads_per_member?.toString() ?? "",
    });
  }, [s]);
  const errors = fieldErrors(error);

  async function save(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/v1/org/settings", {
        method: "PUT",
        body: {
          retention_days: form.retention_days,
          max_file_mb: optional(form.max_file_mb),
          storage_quota_mb: optional(form.storage_quota_mb),
          daily_uploads_per_member: optional(form.daily_uploads_per_member),
        },
      });
      toast("Settings saved. They apply to new uploads.");
      void queryClient.invalidateQueries({ queryKey: ["org-settings"] });
      void queryClient.invalidateQueries({ queryKey: ["org-usage"] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  if (settings.isPending) return <LoadingState />;
  if (settings.isError || !s) return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm({ ...form, [key]: e.target.value });
    setError(null);
  };

  return (
    <div>
      <PageHeader eyebrow="Administration" title="Settings" description="Storage and upload limits for this organisation. Changes apply to new uploads; files already stored keep their expiry date." />
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
        <Card title="Retention and limits">
          <form className="space-y-6" onSubmit={(e) => void save(e)}>
            <fieldset>
              <legend className="text-sm font-bold text-ink">Keep redacted files for</legend>
              <div role="radiogroup" aria-label="Retention" className="mt-2 inline-flex rounded-full border border-rule bg-card p-0.5 text-sm">
                {s.retention_choices.map((d) => (
                  <button
                    key={d}
                    type="button"
                    role="radio"
                    aria-checked={form.retention_days === d}
                    onClick={() => setForm({ ...form, retention_days: d })}
                    className={cx("relative h-8 rounded-full px-4", form.retention_days === d ? "font-bold text-ink" : "text-ink-3 hover:text-ink")}
                  >
                    {form.retention_days === d && <motion.span layoutId="retention-pill" className="absolute inset-0 rounded-full bg-raised" transition={{ type: "spring", stiffness: 500, damping: 38 }} />}
                    <span className="relative">{d} days</span>
                  </button>
                ))}
              </div>
            </fieldset>
            <Field label="Maximum file size (MB)" hint={`Empty means the server maximum, ${s.server_max_file_mb} MB.`} error={errors.max_file_mb}>
              {(p) => <Input {...p} type="number" min={1} max={s.server_max_file_mb} inputMode="numeric" placeholder={String(s.server_max_file_mb)} value={form.max_file_mb} onChange={set("max_file_mb")} />}
            </Field>
            <Field label="Storage quota (MB)" hint="Uploads that would go over it are refused. Empty means no quota." error={errors.storage_quota_mb}>
              {(p) => <Input {...p} type="number" min={1} inputMode="numeric" placeholder="No quota" value={form.storage_quota_mb} onChange={set("storage_quota_mb")} />}
            </Field>
            <Field label="Uploads per member per day" hint="Counted over the last 24 hours. Empty means no limit." error={errors.daily_uploads_per_member}>
              {(p) => <Input {...p} type="number" min={1} inputMode="numeric" placeholder="No limit" value={form.daily_uploads_per_member} onChange={set("daily_uploads_per_member")} />}
            </Field>
            {error !== null && Object.keys(errors).length === 0 && <ErrorState error={error} />}
            <Button type="submit" variant="primary" busy={busy}>
              Save settings
            </Button>
          </form>
        </Card>
        <Card title="Storage used">
          <UsageBar used={usage.data?.storage_used_bytes ?? s.storage_used_bytes} quota={usage.data?.storage_quota_bytes ?? (s.storage_quota_mb ? s.storage_quota_mb * 1024 * 1024 : null)} />
          <h3 className="colhead mt-6 mb-2">By member</h3>
          {usage.isPending ? (
            <LoadingState lines={3} />
          ) : usage.isError ? (
            <ErrorState error={usage.error} />
          ) : (
            <table className="w-full text-sm" aria-label="Storage by member">
              <tbody>
                {usage.data.members.map((m, i) => (
                  <motion.tr key={m.user_id ?? "tickets"} className="border-b border-rule" initial={{ opacity: 0, x: 12 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: i * 0.04 }}>
                    <td className="py-2 pr-3">
                      <div className="text-ink">{m.name || m.email}</div>
                      {m.name && m.email && <div className="text-xs text-ink-3">{m.email}</div>}
                    </td>
                    <td className="py-2 pr-3 text-right font-mono text-xs text-ink-3">
                      {m.files === null ? null : `${m.files} file${m.files === 1 ? "" : "s"}`}
                    </td>
                    <td className="py-2 text-right font-mono text-ink-2">{bytes(m.bytes)}</td>
                  </motion.tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}
