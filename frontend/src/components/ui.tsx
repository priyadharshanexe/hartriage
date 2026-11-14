import { type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, useEffect, useId, useState } from "react";
import { ApiError, errorMessage } from "../lib/api";
import { splitMarkers } from "../lib/format";
import type { Severity } from "../lib/types";

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------------- Button
type Variant = "primary" | "secondary" | "danger" | "ghost";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-ink text-paper hover:bg-ink-2 disabled:bg-ink-4",
  secondary: "border border-ink/80 bg-transparent text-ink hover:bg-ink hover:text-paper disabled:border-ink-4 disabled:text-ink-4 disabled:hover:bg-transparent",
  danger: "bg-high text-white hover:bg-critical disabled:opacity-50",
  ghost: "text-ink-2 hover:bg-paper-2 hover:text-ink disabled:text-ink-4",
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
        "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-[2px] font-medium transition-colors disabled:cursor-not-allowed",
        size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-4 text-sm",
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

// ---------------------------------------------------------------------- Fields
interface FieldProps {
  label: string;
  hint?: ReactNode;
  error?: string;
  children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode;
}

export function Field({ label, hint, error, children }: FieldProps) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div>
      <label htmlFor={id} className="eyebrow mb-1.5 block">
        {label}
      </label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {hint && !error && (
        <p id={`${id}-hint`} className="mt-1.5 text-xs text-ink-3">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="mt-1.5 text-xs font-medium text-high">
          {error}
        </p>
      )}
    </div>
  );
}

const INPUT =
  "block rounded-[2px] border border-rule-2 bg-card px-3 py-2 text-sm text-ink placeholder:text-ink-4 focus:border-ink focus:outline-none disabled:cursor-not-allowed disabled:bg-paper-2 disabled:text-ink-3 aria-[invalid=true]:border-high";

/** Full width unless the caller sets a width. */
function width(className: string | undefined): string {
  return className && /(^|\s)(max-)?w-/.test(className) ? "" : "w-full";
}

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cx(INPUT, width(className), className)} {...rest} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx(INPUT, width(className), "pr-8", className)} {...rest}>
      {children}
    </select>
  );
}

// ---------------------------------------------------------------------- Tags
type Tone = "ink" | "ok" | "warn" | "bad" | "muted" | "signal";
const TONES: Record<Tone, string> = {
  ink: "border-ink bg-ink text-paper",
  ok: "border-ok/40 bg-ok/10 text-ok",
  warn: "border-medium/50 bg-medium/15 text-[#7a5600]",
  bad: "border-high/40 bg-high/10 text-high",
  muted: "border-rule-2 bg-paper-2 text-ink-2",
  signal: "border-signal/40 bg-signal-soft text-signal",
};

export function Tag({ tone = "muted", children, title, className }: { tone?: Tone; children: ReactNode; title?: string; className?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center rounded-[2px] border px-1.5 py-px font-mono text-[0.7rem] leading-5", TONES[tone], className)}>
      {children}
    </span>
  );
}

const SEVERITY_STYLE: Record<Severity, string> = {
  critical: "bg-critical text-white",
  high: "bg-high text-white",
  medium: "bg-medium text-ink",
  info: "bg-info text-white",
};

/** A triage tag: the colour says how urgent, the word says it again for colour-blind readers. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span className={cx("inline-flex h-5 items-center gap-1.5 rounded-[2px] pr-2 pl-1.5 font-display text-[0.68rem] font-bold tracking-[0.1em] uppercase", SEVERITY_STYLE[severity])}>
      <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-current opacity-70" />
      {severity}
    </span>
  );
}

// ---------------------------------------------------------------------- States
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
    <div className="flex items-center justify-center gap-3 py-16 font-mono text-sm text-ink-3">
      <Spinner />
      {label}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="border border-dashed border-rule-2 px-6 py-12 text-center">
      <p className="font-display text-lg font-semibold">{title}</p>
      {children && <div className="mx-auto mt-1.5 max-w-md text-sm text-ink-3">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry, action }: { error: unknown; onRetry?: () => void; action?: ReactNode }) {
  const requestId = error instanceof ApiError && error.status >= 500 ? error.requestId : null;
  const notFound = error instanceof ApiError && error.status === 404;
  return (
    <div role="alert" className="border-l-4 border-high bg-high/[0.07] px-4 py-3">
      <p className="text-sm font-medium text-ink">{errorMessage(error)}</p>
      {requestId && <p className="mt-1 font-mono text-xs text-ink-3">Request ID {requestId}</p>}
      {(action || (onRetry && !notFound)) && (
        <div className="mt-3 flex gap-2">
          {action}
          {onRetry && !notFound && (
            <Button size="sm" onClick={onRetry}>
              Try again
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/** A short-lived confirmation ("Re-run started"). */
export function Notice({ children, onDone, tone = "ok" }: { children: ReactNode; onDone: () => void; tone?: "ok" | "bad" }) {
  useEffect(() => {
    const timer = window.setTimeout(onDone, 4000);
    return () => window.clearTimeout(timer);
  }, [onDone]);
  return (
    <div role="status" className={cx("border-l-4 px-4 py-2.5 text-sm", tone === "ok" ? "border-ok bg-ok/[0.08]" : "border-high bg-high/[0.07]")}>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------- Layout
export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: ReactNode; title: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-4 border-b border-ink pb-5">
      <div className="min-w-0 max-w-3xl">
        {eyebrow && <div className="eyebrow mb-2">{eyebrow}</div>}
        <h1 className="font-display text-3xl font-semibold tracking-tight break-words">{title}</h1>
        {description && <div className="mt-2 text-sm text-ink-2">{description}</div>}
      </div>
      {action && <div className="flex flex-wrap gap-2">{action}</div>}
    </header>
  );
}

export function Card({ title, action, children, className, flush = false }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; flush?: boolean }) {
  return (
    <section className={cx("border border-rule bg-card", className)}>
      {(title || action) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-5 py-3">
          {title && <h2 className="eyebrow">{title}</h2>}
          {action}
        </div>
      )}
      <div className={flush ? "" : "p-5"}>{children}</div>
    </section>
  );
}

/** Text where every redaction marker becomes a redaction bar. */
export function Redacted({ text, className }: { text: string; className?: string }) {
  return (
    <span className={cx("break-words [overflow-wrap:anywhere]", className)}>
      {splitMarkers(text).map((part, i) =>
        part.marker ? (
          <mark key={i} className="redaction" title="Removed before storage. The same id means the same value within this file.">
            {part.text.slice(10, -1)}
          </mark>
        ) : (
          <span key={i}>{part.text}</span>
        ),
      )}
    </span>
  );
}

export function CopyButton({ getText, label = "Copy", copiedLabel = "Copied", variant = "secondary", size = "md" }: { getText: () => Promise<string> | string; label?: string; copiedLabel?: string; variant?: Variant; size?: "sm" | "md" }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "failed">("idle");
  return (
    <Button
      variant={variant}
      size={size}
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
      {state === "done" ? `✓ ${copiedLabel}` : state === "failed" ? "Copy failed" : label}
    </Button>
  );
}

/** A destructive action that asks inline instead of a browser confirm() dialog. */
export function ConfirmButton({ label, confirmLabel = "Yes, do it", question, onConfirm, busy = false, size = "sm" }: { label: string; confirmLabel?: string; question: string; onConfirm: () => void; busy?: boolean; size?: "sm" | "md" }) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <Button size={size} variant="ghost" className="text-high hover:bg-high/10 hover:text-high" onClick={() => setAsking(true)}>
        {label}
      </Button>
    );
  }
  return (
    <span role="group" aria-label={question} className="inline-flex flex-wrap items-center gap-2 border-l-4 border-high bg-high/[0.07] py-1 pr-1 pl-2.5 text-xs text-ink">
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

/** A labelled value in a definition grid. */
export function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="eyebrow">{label}</dt>
      <dd className="mt-1 font-mono text-sm text-ink">{children}</dd>
    </div>
  );
}
