import { type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, useEffect, useId, useState } from "react";
import { motion } from "motion/react";
import { ApiError, errorMessage } from "../lib/api";
import { splitMarkers } from "../lib/format";
import type { Severity } from "../lib/types";

export function cx(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------------- Button
type Variant = "primary" | "secondary" | "danger" | "ghost";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-primary text-on-primary shadow-[0_1px_0_rgb(0_0_0/0.08)] hover:brightness-110 disabled:opacity-50",
  secondary: "border border-rule-2 bg-card text-ink hover:border-ink-3 hover:bg-paper-2 disabled:opacity-50",
  danger: "bg-critical text-white hover:brightness-110 disabled:opacity-50",
  ghost: "text-ink-2 hover:bg-paper-2 hover:text-ink disabled:opacity-50",
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
        "inline-flex shrink-0 items-center justify-center gap-2 rounded-[5px] font-bold whitespace-nowrap transition-[background-color,border-color,filter,transform] duration-150 ease-out active:scale-[0.98] disabled:cursor-not-allowed disabled:active:scale-100",
        size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-sm",
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
      <label htmlFor={id} className="mb-1.5 block text-sm font-bold text-ink-2">
        {label}
      </label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {hint && !error && (
        <p id={`${id}-hint`} className="mt-1.5 text-xs text-ink-3">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="animate-slide-down mt-1.5 text-xs font-bold text-critical">
          {error}
        </p>
      )}
    </div>
  );
}

const INPUT =
  "block h-10 rounded-[5px] border border-rule-2 bg-card px-3 text-base text-ink transition-[border-color,box-shadow] duration-150 placeholder:text-ink-4 focus:border-primary focus:shadow-[0_0_0_3px_var(--primary-soft)] focus:outline-none disabled:cursor-not-allowed disabled:bg-paper-2 disabled:text-ink-3 aria-[invalid=true]:border-critical";

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
  ink: "bg-ink text-paper",
  ok: "bg-ok/12 text-ok",
  warn: "bg-medium/20 text-medium-ink",
  bad: "bg-critical/12 text-critical",
  muted: "bg-paper-2 text-ink-3",
  signal: "bg-signal-soft text-signal",
};

export function Tag({ tone = "muted", children, title, className }: { tone?: Tone; children: ReactNode; title?: string; className?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs leading-5 font-bold", TONES[tone], className)}>
      {children}
    </span>
  );
}

/** An HTTP status, coloured by class, always with its number. */
export function StatusCode({ status, error }: { status: number; error?: string }) {
  const tone = status === 0 || error || status >= 500 ? "text-s5xx" : status >= 400 ? "text-s4xx" : status >= 300 ? "text-s3xx" : "text-s2xx";
  return <span className={cx("font-mono font-medium tabular-nums", tone)}>{status || "ERR"}</span>;
}

const SEVERITY: Record<Severity, { label: string; shape: string; className: string }> = {
  critical: { label: "Critical", shape: "◆", className: "bg-critical text-white" },
  high: { label: "High", shape: "◆", className: "bg-high text-white" },
  medium: { label: "Medium", shape: "◇", className: "bg-medium text-[#171a1f]" },
  info: { label: "Info", shape: "●", className: "bg-info/15 text-info" },
};

/** Severity: colour, word and shape, so colour is never the only signal. */
export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity];
  return (
    <span className={cx("inline-flex h-6 items-center gap-1.5 rounded-full px-2.5 text-xs font-bold", s.className)}>
      <span aria-hidden="true" className="text-[0.7rem] leading-none">
        {s.shape}
      </span>
      {s.label}
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

/** Placeholder lines while loading (a shimmer; static under reduced motion). */
export function LoadingState({ label = "Loading…", lines = 4 }: { label?: string; lines?: number }) {
  return (
    <div role="status" aria-label={label} className="space-y-3 py-6">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skeleton h-4" style={{ width: `${[92, 78, 85, 60, 70][i % 5]}%` }} />
      ))}
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="animate-rise rounded-[8px] border border-dashed border-rule-2 px-6 py-12 text-center">
      <p className="font-display text-xl font-medium">{title}</p>
      {children && <div className="mx-auto mt-2 max-w-md text-sm text-ink-3">{children}</div>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry, action }: { error: unknown; onRetry?: () => void; action?: ReactNode }) {
  const requestId = error instanceof ApiError && error.status >= 500 ? error.requestId : null;
  const notFound = error instanceof ApiError && error.status === 404;
  return (
    <div role="alert" className="animate-slide-down rounded-[6px] border border-critical/30 bg-critical/8 px-4 py-3">
      <p className="text-sm font-bold text-ink">{errorMessage(error)}</p>
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

/** A short-lived confirmation ("Re-run finished"). */
export function Notice({ children, onDone, tone = "ok" }: { children: ReactNode; onDone: () => void; tone?: "ok" | "bad" }) {
  useEffect(() => {
    const timer = window.setTimeout(onDone, 4000);
    return () => window.clearTimeout(timer);
  }, [onDone]);
  return (
    <motion.div
      role="status"
      initial={{ opacity: 0, y: -14, scale: 0.97 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8 }}
      transition={{ type: "spring", stiffness: 420, damping: 28 }}
      className={cx(
        "flex items-center gap-2 rounded-[8px] px-4 py-2.5 text-sm",
        tone === "ok" ? "bg-ok/10 text-ink" : "border border-critical/30 bg-critical/8 text-ink",
      )}
    >
      {tone === "ok" && (
        <span aria-hidden="true" className="animate-tick font-bold text-ok">
          ✓
        </span>
      )}
      {children}
    </motion.div>
  );
}

// ---------------------------------------------------------------------- Layout
export function PageHeader({ eyebrow, title, description, action }: { eyebrow?: ReactNode; title: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0 max-w-3xl">
        {eyebrow && <div className="eyebrow mb-1">{eyebrow}</div>}
        {/* Page titles are wiped into view from the left (a mask reveal). */}
        <motion.h1
          className="font-display text-[2.5rem] leading-[1.08] font-semibold tracking-[-0.02em] break-words"
          initial={{ clipPath: "inset(0 100% 0 0)", x: -6 }}
          animate={{ clipPath: "inset(0 0% 0 0)", x: 0 }}
          transition={{ duration: 0.55, ease: [0.2, 0.7, 0.2, 1] }}
        >
          {title}
        </motion.h1>
        {description && <div className="mt-2 text-base text-ink-3">{description}</div>}
      </div>
      {action && <div className="flex flex-wrap gap-2">{action}</div>}
    </header>
  );
}

export function Card({ title, action, children, className, flush = false }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; flush?: boolean }) {
  return (
    <section className={cx("animate-rise rounded-[8px] border border-rule bg-card", className)}>
      {(title || action) && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-rule px-5 py-3">
          {title && <h2 className="text-base font-bold">{title}</h2>}
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
      {state === "done" ? (
        <>
          <span aria-hidden="true" className="animate-tick">
            ✓
          </span>
          {copiedLabel}
        </>
      ) : state === "failed" ? (
        "Copy failed"
      ) : (
        label
      )}
    </Button>
  );
}

/** A destructive action that asks inline instead of a browser confirm() dialog. */
export function ConfirmButton({ label, confirmLabel = "Yes, do it", question, onConfirm, busy = false, size = "sm" }: { label: string; confirmLabel?: string; question: string; onConfirm: () => void; busy?: boolean; size?: "sm" | "md" }) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return (
      <Button size={size} variant="ghost" className="text-critical hover:bg-critical/10 hover:text-critical" onClick={() => setAsking(true)}>
        {label}
      </Button>
    );
  }
  return (
    <span role="group" aria-label={question} className="animate-slide-down inline-flex flex-wrap items-center gap-2 rounded-[6px] bg-critical/8 py-1 pr-1 pl-3 text-sm text-ink">
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
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="mt-0.5 font-mono text-sm text-ink tabular-nums">{children}</dd>
    </div>
  );
}
