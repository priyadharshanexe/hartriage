import { type FormEvent, type ReactNode, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { Logo } from "../components/Layout";
import { Button, ErrorState, Field, Input } from "../components/ui";
import { api, fieldErrors } from "../lib/api";
import type { Session } from "../lib/types";

function Shell({ title, children, footer }: { title: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center px-4 py-12">
      <Logo />
      <div className="mt-6 w-full max-w-sm rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <h1 className="mb-4 text-lg font-semibold">{title}</h1>
        {children}
      </div>
      {footer && <p className="mt-4 text-sm text-slate-600">{footer}</p>}
      <p className="mt-8 max-w-sm text-center text-xs text-slate-500">
        HAR files carry session cookies and tokens. HAR Triage removes them before anything is stored.
      </p>
    </div>
  );
}

function useSubmit(path: string, after: string) {
  const { setSession } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  async function submit(body: unknown) {
    setBusy(true);
    setError(null);
    try {
      const session = await api<Session>(path, { method: "POST", body, skipRefresh: true });
      setSession(session);
      navigate(after, { replace: true });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return { submit, error, busy };
}

export function LoginPage() {
  const { session } = useAuth();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const { submit, error, busy } = useSubmit("/v1/auth/login", from);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  if (session) return <Navigate to={from} replace />;
  return (
    <Shell title="Sign in" footer={<>New here? <Link className="font-medium text-brand-700" to="/register">Create an organisation</Link></>}>
      <form
        className="space-y-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void submit({ email, password });
        }}
      >
        <Field label="Email">{(p) => <Input {...p} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
        <Field label="Password">
          {(p) => <Input {...p} type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />}
        </Field>
        {error !== null && <ErrorState error={error} />}
        <Button type="submit" variant="primary" className="w-full" busy={busy}>
          Sign in
        </Button>
      </form>
    </Shell>
  );
}

export function RegisterPage() {
  const { session } = useAuth();
  const { submit, error, busy } = useSubmit("/v1/auth/register", "/");
  const [form, setForm] = useState({ name: "", email: "", password: "", organization: "" });
  const errors = fieldErrors(error);
  if (session) return <Navigate to="/" replace />;
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value });
  return (
    <Shell title="Create an organisation" footer={<>Have an account? <Link className="font-medium text-brand-700" to="/login">Sign in</Link></>}>
      <form
        className="space-y-4"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void submit(form);
        }}
      >
        <Field label="Your name">{(p) => <Input {...p} autoComplete="name" value={form.name} onChange={set("name")} />}</Field>
        <Field label="Work email" error={errors.email}>{(p) => <Input {...p} type="email" required value={form.email} onChange={set("email")} />}</Field>
        <Field label="Password" hint="At least 10 characters." error={errors.password}>
          {(p) => <Input {...p} type="password" autoComplete="new-password" required minLength={10} value={form.password} onChange={set("password")} />}
        </Field>
        <Field label="Team or company name" error={errors.organization}>{(p) => <Input {...p} required value={form.organization} onChange={set("organization")} />}</Field>
        {error !== null && Object.keys(errors).length === 0 && <ErrorState error={error} />}
        <Button type="submit" variant="primary" className="w-full" busy={busy}>
          Create organisation
        </Button>
      </form>
    </Shell>
  );
}

export function InvitePage() {
  const token = window.location.hash.slice(1);
  const { submit, error, busy } = useSubmit("/v1/auth/accept-invite", "/");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  return (
    <Shell title="Join your team">
      {!token ? (
        <p className="text-sm text-slate-600">This link is incomplete. Open the full invitation link you were sent.</p>
      ) : (
        <form
          className="space-y-4"
          onSubmit={(e: FormEvent) => {
            e.preventDefault();
            void submit({ token, name, password });
          }}
        >
          <Field label="Your name">{(p) => <Input {...p} value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <Field label="Choose a password" hint="At least 10 characters. If you already have an account, enter its password.">
            {(p) => <Input {...p} type="password" required minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} />}
          </Field>
          {error !== null && <ErrorState error={error} />}
          <Button type="submit" variant="primary" className="w-full" busy={busy}>
            Join
          </Button>
        </form>
      )}
    </Shell>
  );
}
