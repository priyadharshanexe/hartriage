/**
 * Behind the sign-in form: sample HAR lines drift past and their secrets are blacked
 * out one by one, in real time. Clearly sample data (made-up hosts and values), drawn
 * from the product's own action. Static, fully redacted, under reduced motion.
 */
import { useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import { cx } from "./ui";

const HEADERS = [
  ["authorization", "Bearer "],
  ["cookie", "session="],
  ["x-api-key", ""],
  ["set-cookie", "refresh="],
  ["x-csrf-token", ""],
  ["proxy-authorization", "Basic "],
] as const;
const PLAIN = [
  "GET https://app.example.test/api/me 401",
  "POST https://api.example.test/v2/orders 201",
  "accept: application/json",
  "x-request-id: req_8c1d42e9",
  "GET https://cdn.example.test/app.css 200",
  "user-agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6)",
  "OPTIONS https://api.example.test/v2/cart 204",
  "content-type: application/json; charset=utf-8",
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

function makeLines(count: number): Line[] {
  const rnd = seeded(7);
  const hex = () => Math.floor(rnd() * 0xffffffff).toString(16).padStart(8, "0");
  const blob = (len: number) =>
    Array.from({ length: len }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"[Math.floor(rnd() * 62)]).join("");
  return Array.from({ length: count }, (_, i) => {
    if (i % 3 === 1) {
      const [name, prefix] = HEADERS[Math.floor(rnd() * HEADERS.length)]!;
      return { text: `${name}: `, secret: { prefix, value: `eyJ${blob(18)}`, marker: hex() } };
    }
    return { text: PLAIN[Math.floor(rnd() * PLAIN.length)]! };
  });
}

export function RedactionField() {
  const reduce = useReducedMotion();
  const lines = useMemo(() => makeLines(36), []);
  const secretIdx = useMemo(() => lines.flatMap((l, i) => (l.secret ? [i] : [])), [lines]);
  const [stamped, setStamped] = useState<Set<number>>(() => new Set(reduce ? secretIdx : []));

  useEffect(() => {
    if (reduce) {
      setStamped(new Set(secretIdx));
      return;
    }
    // Black out one secret every ~0.7 s; when all are out, start over.
    const timer = window.setInterval(() => {
      setStamped((prev) => {
        const left = secretIdx.filter((i) => !prev.has(i));
        if (left.length === 0) return new Set();
        const next = new Set(prev);
        next.add(left[Math.floor(Math.random() * left.length)]!);
        return next;
      });
    }, 700);
    return () => window.clearInterval(timer);
  }, [reduce, secretIdx]);

  const column = (
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
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden select-none">
      <div className="absolute inset-y-0 right-0 w-full font-mono text-[0.8125rem] leading-6 text-ink-4 opacity-20 lg:opacity-60 [mask-image:linear-gradient(to_right,transparent,black_35%,black)] lg:w-[62%]">
        <div className={cx("px-8", !reduce && "animate-drift")}>
          {column}
          {column}
        </div>
      </div>
    </div>
  );
}
