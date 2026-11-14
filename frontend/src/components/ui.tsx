import { type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, useId, useState } from "react";
import { ApiError, errorMessage } from "../lib/api";
import { splitMarkers } from "../lib/format";
import type { Severity } from "../lib/types";

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "danger" | "ghost";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:bg-brand-600/50",
  secondary: "bg-white text-slate-700 ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:text-slate-400",
  danger: "bg-red-600 text-white hover:bg-red-700 disabled:bg-red-600/50",
  ghost: "text-slate-600 hover:bg-slate-100 disabled:text-slate-400",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  busy?: boolean;
}

export function Button({ variant = "secondary", size = "md", busy = false, disabled, className, children, type = "button", ...rest }: ButtonProps) {
  return (
    <button
      type={type}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={cx(
        "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-md font-medium transition-colors disabled:cursor-not-allowed",
        size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm",
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {busy && <Spinner small />}
      {children}
    </button>
  );
}

interface FieldProps {
  label: string;
  hint?: string;
  error?: string;
  children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode;
}

export function Field({ label, hint, error, children }: FieldProps) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-700">
        {label}
      </label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {hint && !error && (
        <p id={`${id}-hint`} className="mt-1 text-xs text-slate-500">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="mt-1 text-xs text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}

const INPUT =
  "block w-full rounded-md border-0 bg-white px-3 py-2 text-sm text-slate-900 ring-1 ring-inset ring-slate-300 placeholder:text-slate-400 aria-[invalid=true]:ring-red-500";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cx(INPUT, className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx(INPUT, "pr-8", className)} {...rest}>
      {children}
    </select>
  );
}

type Tone = "green" | "red" | "amber" | "slate" | "blue" | "purple";
const TONES: Record<Tone, string> = {
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  red: "bg-red-50 text-red-700 ring-red-600/20",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/20",
  slate: "bg-slate-100 text-slate-600 ring-slate-500/20",
  blue: "bg-brand-50 text-brand-700 ring-brand-600/20",
  purple: "bg-violet-50 text-violet-700 ring-violet-600/20",
};

export function Badge({ tone = "slate", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", TONES[tone])}>
      {children}
    </span>
  );
}

const SEVERITY_TONE: Record<Severity, Tone> = { critical: "purple", high: "red", medium: "amber", info: "slate" };

export function SeverityBadge({ severity }: { severity: Severity }) {
  return <Badge tone={SEVERITY_TONE[severity]}>{severity}</Badge>;
}

export function Spinner({ small = false }: { small?: boolean }) {
  return (
    <span
      role="status"
      aria-label="Loading"
      className={cx("inline-block animate-spin rounded-full border-2 border-current border-r-transparent", small ? "h-3.5 w-3.5" : "h-5 w-5")}
    />
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-16 text-sm text-slate-500">
      <Spinner />
      {label}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white px-6 py-12 text-center">
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      {children && <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const requestId = error instanceof ApiError && error.status >= 500 ? error.requestId : null;
  return (
    <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-4 py-3">
      <p className="text-sm font-medium text-red-800">{errorMessage(error)}</p>
      {requestId && <p className="mt-1 font-mono text-xs text-red-700/80">Request ID: {requestId}</p>}
      {onRetry && (
        <Button size="sm" className="mt-3" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function PageHeader({ title, description, action }: { title: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div className="min-w-0">
        <h1 className="break-words text-xl font-semibold text-slate-900">{title}</h1>
        {description && <div className="mt-1 text-sm text-slate-600">{description}</div>}
      </div>
      {action && <div className="flex flex-wrap gap-2">{action}</div>}
    </div>
  );
}

export function Card({ title, action, children, className }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cx("rounded-lg border border-slate-200 bg-white shadow-sm", className)}>
      {(title || action) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3">
          {title && <h2 className="text-sm font-semibold text-slate-900">{title}</h2>}
          {action}
        </div>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

/** Text with redaction markers shown as chips, so nobody mistakes them for real values. */
export function Redacted({ text, className }: { text: string; className?: string }) {
  return (
    <span className={cx("break-all", className)}>
      {splitMarkers(text).map((part, i) =>
        part.marker ? (
          <mark key={i} className="rounded bg-amber-100 px-1 font-mono text-[0.85em] text-amber-900" title="Removed before storage. The same marker means the same value within this file.">
            {part.text}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </span>
  );
}

export function CopyButton({ getText, label = "Copy", copiedLabel = "Copied", variant = "secondary" }: { getText: () => Promise<string> | string; label?: string; copiedLabel?: string; variant?: Variant }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "failed">("idle");
  return (
    <Button
      variant={variant}
      busy={state === "busy"}
      onClick={async () => {
        setState("busy");
        try {
          await navigator.clipboard.writeText(await getText());
          setState("done");
        } catch {
          setState("failed");
        }
        window.setTimeout(() => setState("idle"), 2000);
      }}
    >
      {state === "done" ? copiedLabel : state === "failed" ? "Copy failed" : label}
    </Button>
  );
}

/** A destructive action that asks inline ("Remove? Yes / Cancel") instead of a
 *  browser confirm() dialog, which blocks the page and can't be styled. */
export function ConfirmButton({ label, confirmLabel = "Yes, do it", question, onConfirm, busy = false, size = "sm" }: { label: string; confirmLabel?: string; question: string; onConfirm: () => void; busy?: boolean; size?: "sm" | "md" }) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <Button size={size} variant="ghost" className="text-red-700 hover:bg-red-50" onClick={() => setAsking(true)}>
        {label}
      </Button>
    );
  }
  return (
    <span role="group" aria-label={question} className="inline-flex items-center gap-2 rounded-md bg-red-50 px-2 py-1 text-xs text-red-800">
      {question}
      <Button size="sm" variant="danger" busy={busy} onClick={() => { onConfirm(); setAsking(false); }}>
        {confirmLabel}
      </Button>
      <Button size="sm" variant="ghost" onClick={() => setAsking(false)}>
        Cancel
      </Button>
    </span>
  );
}
