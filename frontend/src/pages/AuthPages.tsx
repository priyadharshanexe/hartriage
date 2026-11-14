import { useQuery } from "@tanstack/react-query";
import { type FormEvent, type ReactNode, useState } from "react";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { Logo } from "../components/Layout";
import { Button, ErrorState, Field, Input, LoadingState } from "../components/ui";
import { api, fieldErrors } from "../lib/api";
import { dateTime } from "../lib/format";
import type { Role, Session } from "../lib/types";

/** A redacted line of a request, as the sign-in pages' side panel shows it. */
function SpecimenLine({ name, value }: { name: string; value: ReactNode }) {
  return (
    <div className="flex gap-3 border-b border-white/10 py-2 font-mono text-xs">
      <span className="w-28 shrink-0 text-[#8a8475]">{name}</span>
      <span className="min-w-0 break-words text-[#e6e0d2]">{value}</span>
    </div>
  );
}

function Shell({ title, lede, children, footer }: { title: string; lede?: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="flex flex-col px-6 py-8 sm:px-12">
        <Logo />
        <div className="flex flex-1 items-center">
          <div className="w-full max-w-sm py-12">
            <h1 className="font-display text-4xl font-semibold tracking-tight">{title}</h1>
            {lede && <div className="mt-2 text-sm text-ink-2">{lede}</div>}
            <div className="mt-8">{children}</div>
            {footer && <p className="mt-6 border-t border-rule pt-4 text-sm text-ink-2">{footer}</p>}
          </div>
        </div>
        <p className="max-w-sm text-xs text-ink-3">HAR files carry session cookies and tokens. HAR Triage removes them before anything is stored.</p>
      </div>
      <aside aria-hidden="true" className="hidden flex-col justify-center bg-ink px-12 py-10 text-paper lg:flex">
        <div className="max-w-md">
          <p className="eyebrow text-[#8a8475]">Request #212 · after redaction</p>
          <p className="mt-3 font-mono text-sm text-paper">
            <span className="mr-2 bg-high px-1.5 py-px text-white">401</span>GET api.example.com/v1/me
          </p>
          <div className="mt-5">
            <SpecimenLine name="authorization" value={<>Bearer <span className="redaction">3f9a01c2</span></>} />
            <SpecimenLine name="cookie" value={<>session=<span className="redaction">b71e04aa</span></>} />
            <SpecimenLine name="x-request-id" value="req_8c1d42" />
            <SpecimenLine name="www-authenticate" value='Bearer error="invalid_token"' />
          </div>
          <p className="mt-8 font-display text-2xl leading-snug font-medium">
            The token <span className="redaction">3f9a01c2</span> expired 4 minutes before this request.
          </p>
          <p className="mt-3 text-sm text-[#b8b19f]">Find the failing request, see why it failed, and paste the answer into the ticket.</p>
        </div>
      </aside>
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

const LINK = "font-medium text-ink underline decoration-signal decoration-2 underline-offset-2 hover:text-signal";

export function LoginPage() {
  const { session } = useAuth();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const { submit, error, busy, clearError } = useSubmit("/v1/auth/login", from);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  if (session) return <Navigate to={from} replace />;
  return (
    <Shell title="Sign in" lede="Open the case files for your team." footer={<>New here? <Link className={LINK} to="/register">Create an organisation</Link></>}>
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
        <div role="alert" className="mb-6 border-l-4 border-medium bg-medium/15 px-4 py-3 text-sm">
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
