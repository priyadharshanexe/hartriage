/** What HAR Triage does, in four real features, each with a small looping glyph in the
 *  product's own language (redaction bar, highlighter, request bars). Static under
 *  reduced motion. */

function RedactGlyph() {
  return (
    <svg viewBox="0 0 40 24" className="h-6 w-10" aria-hidden="true">
      <rect x="2" y="9" width="36" height="6" rx="3" className="fill-ink-4/40" />
      <rect x="8" y="7" width="22" height="10" rx="2" fill="#000" className="glyph-stamp" style={{ stroke: "#8a93a0", strokeWidth: 1 }} />
    </svg>
  );
}

function RulesGlyph() {
  return (
    <svg viewBox="0 0 40 24" className="h-6 w-10" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <circle key={i} cx={8 + i * 12} cy="12" r="4.5" className="glyph-blink fill-ok" style={{ animationDelay: `${i * 0.35}s` }} />
      ))}
    </svg>
  );
}

function WaterfallGlyph() {
  return (
    <svg viewBox="0 0 40 24" className="h-6 w-10" aria-hidden="true">
      {[
        [2, 3, 16],
        [8, 10, 20],
        [14, 17, 22],
      ].map(([x, y, w], i) => (
        <rect key={i} x={x} y={y} width={w} height="4" rx="2" className="glyph-grow fill-primary" style={{ animationDelay: `${i * 0.25}s` }} />
      ))}
    </svg>
  );
}

function NoteGlyph() {
  return (
    <svg viewBox="0 0 40 24" className="h-6 w-10" aria-hidden="true">
      <rect x="6" y="2" width="28" height="20" rx="3" className="fill-none stroke-ink-4" strokeWidth="1.5" />
      <rect x="10" y="8" width="20" height="4" rx="1" className="glyph-sweep fill-highlight" />
      <rect x="10" y="15" width="14" height="2" rx="1" className="fill-ink-4/60" />
    </svg>
  );
}

const POINTS = [
  { glyph: <RedactGlyph />, title: "Secrets out before storage", body: "Cookies, tokens, keys and passwords become markers as the file streams in." },
  { glyph: <RulesGlyph />, title: "11 diagnostic rules", body: "Expired tokens, CORS, redirects, timeouts, rate limits, payloads and more." },
  { glyph: <WaterfallGlyph />, title: "A waterfall of every request", body: "Up to 50,000 requests, each one a click from its redacted headers." },
  { glyph: <NoteGlyph />, title: "Answers in the ticket", body: "Tag a Zendesk or Freshdesk ticket; a private note arrives with the findings." },
];

export function ProofPoints() {
  return (
    <ul className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
      {POINTS.map((p, i) => (
        <li key={p.title} className="animate-rise flex gap-3" style={{ animationDelay: `${300 + i * 90}ms` }}>
          <span className="mt-0.5 shrink-0">{p.glyph}</span>
          <span className="min-w-0">
            <span className="block text-sm font-bold text-ink">{p.title}</span>
            <span className="block text-[0.8125rem] leading-snug text-ink-3">{p.body}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}
