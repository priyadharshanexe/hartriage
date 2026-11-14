import type { Phase, Severity } from "./types";

export function bytes(n: number | null | undefined): string {
  if (n === null || n === undefined || n <= 0) return "—";
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

export function ms(value: number | null | undefined): string {
  if (value === null || value === undefined || value < 0) return "—";
  if (value >= 60_000) return `${(value / 60_000).toFixed(1)} min`;
  if (value >= 1000) return `${(value / 1000).toFixed(2)} s`;
  if (value > 0 && value < 10) return `${value.toFixed(1)} ms`;
  return `${Math.round(value)} ms`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function relative(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const diff = new Date(iso).getTime() - now;
  const abs = Math.abs(diff);
  const units: [number, Intl.RelativeTimeFormatUnit][] = [
    [86_400_000, "day"],
    [3_600_000, "hour"],
    [60_000, "minute"],
  ];
  const fmt = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  for (const [size, unit] of units) {
    if (abs >= size) return fmt.format(Math.round(diff / size), unit);
  }
  return fmt.format(Math.round(diff / 1000), "second");
}

export function epoch(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  return new Date(seconds * 1000).toISOString().replace("T", " ").replace(/\.\d+Z$/, " UTC");
}

export const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "info"];

export const PHASES: Phase[] = ["blocked", "dns", "connect", "ssl", "send", "wait", "receive"];

export const PHASE_LABEL: Record<Phase, string> = {
  blocked: "Queued",
  dns: "DNS",
  connect: "Connect",
  ssl: "TLS",
  send: "Send",
  wait: "Waiting (server)",
  receive: "Download",
};

/** Exclusive phase durations: in HAR, `connect` includes the TLS handshake. */
export function phaseDurations(timings: Partial<Record<Phase, number | null>>): Partial<Record<Phase, number>> {
  const out: Partial<Record<Phase, number>> = {};
  for (const phase of PHASES) {
    let value = timings[phase];
    if (value === null || value === undefined || value < 0) continue;
    if (phase === "connect") {
      const ssl = timings.ssl;
      if (ssl !== null && ssl !== undefined && ssl > 0) value = Math.max(0, value - ssl);
    }
    out[phase] = value;
  }
  return out;
}

export function statusTone(status: number, error: string): "green" | "amber" | "red" | "slate" {
  if (status === 0 || error) return "red";
  if (status >= 500) return "red";
  if (status >= 400) return "amber";
  if (status >= 300) return "slate";
  return "green";
}

export const MARKER = /\[REDACTED:[0-9a-f]{8}\]/g;

/** Split text around redaction markers, so the UI can style each marker. */
export function splitMarkers(text: string): { text: string; marker: boolean }[] {
  const parts: { text: string; marker: boolean }[] = [];
  let last = 0;
  for (const match of text.matchAll(MARKER)) {
    const index = match.index ?? 0;
    if (index > last) parts.push({ text: text.slice(last, index), marker: false });
    parts.push({ text: match[0], marker: true });
    last = index + match[0].length;
  }
  if (last < text.length) parts.push({ text: text.slice(last), marker: false });
  return parts;
}

export function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    return `${u.pathname}${u.search}` || "/";
  } catch {
    return url;
  }
}
