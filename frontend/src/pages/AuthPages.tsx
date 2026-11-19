import { useQuery } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { Logo, ThemeToggle } from "../components/Layout";
import { RedactionField } from "../components/RedactionField";
import { Button, ErrorState, Field, Input, LoadingState } from "../components/ui";
import { api, fieldErrors } from "../lib/api";
import { dateTime } from "../lib/format";
import type { Role, Session } from "../lib/types";

function Shell({ title, lede, children, footer }: { title: string; lede?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden px-5 py-8 sm:px-10">
      <RedactionField />
      <div className="relative flex items-center justify-between">
        <Logo />
        <ThemeToggle />
      </div>
      <main className="relative flex w-full max-w-[30rem] flex-1 flex-col justify-center py-12 lg:ml-[6vw]">
        {/* The product in one line: a secret, removed before anything is stored. */}
        <p className="animate-rise font-display text-[2.1rem] leading-[1.08] font-semibold tracking-[-0.02em] text-ink sm:text-[2.9rem]">
          Every HAR file carries someone&rsquo;s <span className="redact-word">session</span>. We take it out first.
        </p>
        <div className="animate-rise mt-10 rounded-[16px] border border-rule bg-card/95 p-6 shadow-[0_24px_60px_-30px_rgb(0_0_0/0.6)] backdrop-blur-sm sm:p-8" style={{ animationDelay: "120ms" }}>
          <h1 className="font-display text-3xl font-semibold">{title}</h1>
          {lede && <div className="mt-1.5 text-sm text-ink-3">{lede}</div>}
          <div className="mt-6">{children}</div>
        </div>
        {footer && (
          <p className="animate-fade mt-5 text-sm text-ink-3" style={{ animationDelay: "240ms" }}>
            {footer}
          </p>
        )}
      </main>
      <p className="relative max-w-[30rem] text-xs text-ink-4 lg:ml-[6vw]">
        Behind this form: sample request lines, with their secrets replaced the way your files are. Only the redacted copy of a file is ever kept.
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
  return { submit, error, busy, clearError: () => setError(null) };
}

const LINK = "font-bold text-signal underline-offset-2 hover:underline";

export function LoginPage() {
  const { session } = useAuth();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const { submit, error, busy, clearError } = useSubmit("/v1/auth/login", from);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  if (session) return <Navigate to={from} replace />;
  return (
    <Shell title="Sign in" lede="Welcome back." footer={<>New here? <Link className={LINK} to="/register">Create an organisation</Link></>}>
      <form
        className="space-y-5"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void submit({ email, password });
        }}
      >
        <Field label="Email">
          {(p) => <Input {...p} type="email" autoComplete="email" required value={email} onChange={(e) => { setEmail(e.target.value); clearError(); }} />}
        </Field>
        <Field label="Password">
          {(p) => <Input {...p} type="password" autoComplete="current-password" required value={password} onChange={(e) => { setPassword(e.target.value); clearError(); }} />}
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
  const { submit, error, busy, clearError } = useSubmit("/v1/auth/register", "/");
  const [form, setForm] = useState({ name: "", email: "", password: "", organization: "" });
  const errors = fieldErrors(error);
  if (session) return <Navigate to="/" replace />;
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm({ ...form, [key]: e.target.value });
    clearError();
  };
  return (
    <Shell title="Create an organisation" lede="You will be its first admin. Invite the rest of the team afterwards." footer={<>Have an account? <Link className={LINK} to="/login">Sign in</Link></>}>
      <form
        className="space-y-5"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void submit(form);
        }}
      >
        <Field label="Your name">{(p) => <Input {...p} autoComplete="name" value={form.name} onChange={set("name")} />}</Field>
        <Field label="Work email" error={errors.email}>{(p) => <Input {...p} type="email" autoComplete="email" required value={form.email} onChange={set("email")} />}</Field>
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

interface InvitationLookup {
  organization: string;
  email: string;
  role: Role;
  expires_at: string;
  existing_account: boolean;
}

export function InvitePage() {
  const token = window.location.hash.slice(1);
  const { session, logout } = useAuth();
  const { submit, error, busy } = useSubmit("/v1/auth/accept-invite", "/");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const lookup = useQuery({
    queryKey: ["invitation", token],
    queryFn: () => api<InvitationLookup>(`/v1/invitations/lookup?token=${encodeURIComponent(token)}`, { skipRefresh: true }),
    enabled: Boolean(token),
    retry: false,
  });
  const invite = lookup.data;

  if (!token) {
    return (
      <Shell title="Join your team">
        <p className="text-sm text-ink-2">This link is incomplete. Open the full invitation link you were sent.</p>
      </Shell>
    );
  }
  if (lookup.isPending) return <Shell title="Join your team"><LoadingState label="Checking the invitation…" /></Shell>;
  if (lookup.isError || !invite) {
    return (
      <Shell title="Join your team" footer={<Link className={LINK} to="/login">Go to sign in</Link>}>
        <ErrorState error={lookup.error ?? new Error("This invitation is no longer valid.")} />
      </Shell>
    );
  }
  return (
    <Shell
      title={`Join ${invite.organization}`}
      lede={
        <>
          You were invited as <strong className="font-semibold text-ink">{invite.role}</strong>. The invitation expires {dateTime(invite.expires_at)}.
        </>
      }
    >
      {session && session.user.email.toLowerCase() !== invite.email.toLowerCase() && (
        <div role="alert" className="animate-slide-down mb-6 rounded-[6px] bg-medium/15 px-4 py-3 text-sm">
          You are signed in as <span className="font-mono">{session.user.email}</span>, but this invitation is for <span className="font-mono">{invite.email}</span>.
          <div className="mt-2">
            <Button size="sm" onClick={() => void logout()}>
              Sign out first
            </Button>
          </div>
        </div>
      )}
      <form
        className="space-y-5"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          void submit({ token, name, password });
        }}
      >
        <Field label="Email">{(p) => <Input {...p} value={invite.email} readOnly disabled />}</Field>
        {!invite.existing_account && <Field label="Your name">{(p) => <Input {...p} autoComplete="name" value={name} onChange={(e) => setName(e.target.value)} />}</Field>}
        <Field
          label={invite.existing_account ? "Your password" : "Choose a password"}
          hint={invite.existing_account ? "You already have an account: enter its password." : "At least 10 characters."}
        >
          {(p) => (
            <Input
              {...p}
              type="password"
              autoComplete={invite.existing_account ? "current-password" : "new-password"}
              required
              minLength={10}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          )}
        </Field>
        {error !== null && <ErrorState error={error} />}
        <Button type="submit" variant="primary" className="w-full" busy={busy}>
          Join {invite.organization}
        </Button>
      </form>
    </Shell>
  );
}
