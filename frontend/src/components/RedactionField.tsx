/**
 * Behind the sign-in form: sample HAR lines drift past and their secrets are blacked
 * out, in real time. Clearly sample data (made-up hosts and values). Each column has
 * its own lines (a seeded shuffle of a large pool), its own speed, starting offset,
 * opacity and stamping rhythm, so no two columns ever line up. Static and fully
 * redacted under reduced motion.
 */
import { useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { cx } from "./ui";

const HOSTS = ["app.example.test", "api.example.test", "cdn.example.test", "auth.example.test", "billing.example.test", "ws.example.test", "img.example.test"];
const PATHS = ["/api/me", "/v2/orders", "/v2/cart", "/login", "/oauth/token", "/static/app.js", "/graphql", "/v1/invoices/7731", "/health", "/socket", "/v2/search?q=shoes", "/avatar/42.png", "/v1/session/refresh", "/export.csv"];
const METHODS = ["GET", "GET", "GET", "POST", "PUT", "OPTIONS", "DELETE", "PATCH"];
const STATUSES = ["200", "200", "201", "204", "301", "304", "400", "401", "403", "404", "413", "429", "500", "502", "503"];
const PLAIN_HEADERS = [
  "accept: application/json",
  "accept-encoding: gzip, br",
  "content-type: application/json; charset=utf-8",
  "user-agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
  "user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6)",
  "cache-control: no-store",
  "origin: https://app.example.test",
  "retry-after: 30",
  "access-control-allow-origin: *",
  "x-ratelimit-remaining: 0",
  "sec-fetch-mode: cors",
  "referer: https://app.example.test/checkout",
];
const SECRET_HEADERS = [
  ["authorization", "Bearer "],
  ["cookie", "session="],
  ["x-api-key", ""],
  ["set-cookie", "refresh="],
  ["x-csrf-token", ""],
  ["proxy-authorization", "Basic "],
  ["x-amz-security-token", ""],
  ["cookie", "_ga=GA1.2.88; sid="],
  ["x-auth-token", ""],
  ["query.access_token", ""],
] as const;

function seeded(n: number): () => number {
  let x = n;
  return () => {
    x = (x * 1103515245 + 12345) & 0x7fffffff;
    return x / 0x7fffffff;
  };
}

interface Line {
  text: string;
  secret?: { prefix: string; value: string; marker: string };
}

function makeLines(seed: number, count: number): Line[] {
  const rnd = seeded(seed);
  const pick = <T,>(xs: readonly T[]) => xs[Math.floor(rnd() * xs.length)]!;
  const hex = () => Math.floor(rnd() * 0xffffffff).toString(16).padStart(8, "0");
  const blob = (len: number) => Array.from({ length: len }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"[Math.floor(rnd() * 62)]).join("");
  return Array.from({ length: count }, () => {
    const kind = rnd();
    if (kind < 0.32) {
      const [name, prefix] = pick(SECRET_HEADERS);
      return { text: `${name}: `, secret: { prefix, value: `eyJ${blob(10 + Math.floor(rnd() * 12))}`, marker: hex() } };
    }
    if (kind < 0.62) return { text: `${pick(METHODS)} https://${pick(HOSTS)}${pick(PATHS)} ${pick(STATUSES)}` };
    if (kind < 0.78) return { text: `${pick(METHODS)} ${pick(PATHS)} · ${Math.round(rnd() * 3200)} ms · ${Math.round(rnd() * 90)} kB` };
    return { text: pick(PLAIN_HEADERS) };
  });
}

const COLUMNS = [
  { seed: 11, duration: 38, delay: -7, opacity: 1, every: 620 },
  { seed: 29, duration: 52, delay: -31, opacity: 0.8, every: 910 },
  { seed: 47, duration: 45, delay: -18, opacity: 0.9, every: 760 },
  { seed: 83, duration: 60, delay: -44, opacity: 0.75, every: 1130 },
];

function Column({ seed, duration, delay, opacity, every, index }: (typeof COLUMNS)[number] & { index: number }) {
  const reduce = useReducedMotion();
  const lines = useMemo(() => makeLines(seed, 30), [seed]);
  const secretIdx = useMemo(() => lines.flatMap((l, i) => (l.secret ? [i] : [])), [lines]);
  const [stamped, setStamped] = useState<Set<number>>(() => new Set(reduce ? secretIdx : []));

  useEffect(() => {
    if (reduce) {
      setStamped(new Set(secretIdx));
      return;
    }
    // Each column stamps on its own rhythm, starting at its own moment.
    const rnd = seeded(seed * 7);
    let timer = 0;
    const start = window.setTimeout(() => {
      timer = window.setInterval(() => {
        setStamped((prev) => {
          const left = secretIdx.filter((i) => !prev.has(i));
          if (left.length === 0) return new Set();
          const next = new Set(prev);
          next.add(left[Math.floor(rnd() * left.length)]!);
          return next;
        });
      }, every);
    }, index * 230);
    return () => {
      window.clearTimeout(start);
      window.clearInterval(timer);
    };
  }, [reduce, secretIdx, seed, every, index]);

  const block = (
    <div className="space-y-3 py-3">
      {lines.map((l, i) => (
        <div key={i} className="truncate">
          <span>{l.text}</span>
          {l.secret && (
            <>
              <span>{l.secret.prefix}</span>
              <span className="relative inline-block align-baseline">
                <span className={cx("transition-opacity duration-200", stamped.has(i) && "opacity-0")}>{l.secret.value}</span>
                <span
                  className={cx(
                    "absolute inset-y-[-1px] left-0 flex items-center gap-1 rounded-[2px] bg-[#111318] px-1.5 text-[#e6e1d3] transition-[clip-path] duration-300 ease-out",
                    stamped.has(i) ? "[clip-path:inset(0_0_0_0)]" : "[clip-path:inset(0_100%_0_0)]",
                  )}
                  style={{ boxShadow: "var(--redaction-ring)" }}
                >
                  <span className="inline-block h-[0.5em] w-[1.2em] rounded-[1px] bg-black" />
                  {l.secret.marker}
                </span>
              </span>
            </>
          )}
        </div>
      ))}
    </div>
  );

  return (
    <div className={cx("min-w-[24rem] flex-1", index > 1 && "max-lg:hidden", !reduce && "animate-drift")} style={{ opacity, animationDuration: `${duration}s`, animationDelay: `${delay}s` }}>
      {block}
      {block}
    </div>
  );
}

export function RedactionField() {
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden select-none">
      <div className="absolute inset-0 flex gap-10 overflow-hidden px-6 font-mono text-[0.8125rem] leading-6 text-ink-3 opacity-[var(--field-opacity)] [mask-image:linear-gradient(to_right,rgb(0_0_0/0.25),black_70%)]">
        {COLUMNS.map((c, i) => (
          <Column key={c.seed} {...c} index={i} />
        ))}
      </div>
    </div>
  );
}
