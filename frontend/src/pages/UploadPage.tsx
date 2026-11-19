import { useQuery } from "@tanstack/react-query";
import { type DragEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { Button, cx, ErrorState, PageHeader } from "../components/ui";
import { api, uploadFile } from "../lib/api";
import { bytes } from "../lib/format";
import type { Analysis, Redaction } from "../lib/types";

const ACCEPT = ".har,.json,.gz,.zip";
const MAX_BYTES = 100 * 1024 * 1024;

const SECRET_LABELS: Record<string, [string, string]> = {
  tokens: ["token", "tokens"],
  cookies: ["cookie", "cookies"],
  api_keys: ["API key", "API keys"],
  passwords: ["password", "passwords"],
  signatures: ["signature", "signatures"],
  aws_keys: ["AWS key", "AWS keys"],
  private_keys: ["private key", "private keys"],
};

function reducedMotion(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

/** Counts up from 0 to `target` once it is known (instant under reduced motion). */
function useCountUp(target: number, duration = 600): number {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (reducedMotion() || target <= 0) {
      setValue(target);
      return;
    }
    let frame = 0;
    const start = performance.now();
    const step = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      setValue(Math.round(target * (1 - (1 - t) ** 3)));
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [target, duration]);
  return value;
}

function Count({ n, one, many }: { n: number; one: string; many: string }) {
  const shown = useCountUp(n);
  return (
    <li className="animate-rise">
      <span className="font-mono text-lg font-medium text-ink tabular-nums">{shown}</span> <span className="text-ink-3">{n === 1 ? one : many}</span>
    </li>
  );
}

type Stage = "reading" | "removed" | "analysing" | "done";

function Step({ label, state, children }: { label: string; state: "waiting" | "active" | "done"; children?: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span
        aria-hidden="true"
        className={cx(
          "mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[0.65rem] font-bold transition-colors duration-200",
          state === "done" && "border-ok bg-ok text-white",
          state === "active" && "border-primary text-primary",
          state === "waiting" && "border-rule-2 text-transparent",
        )}
      >
        {state === "done" ? <span className="animate-tick">✓</span> : state === "active" ? <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" /> : "·"}
      </span>
      <div className="min-w-0 flex-1">
        <p className={cx("font-bold", state === "waiting" ? "text-ink-4" : "text-ink")}>{label}</p>
        {children}
      </div>
    </li>
  );
}

function Progress({ file, progress, analysis }: { file: File | null; progress: number; analysis: Analysis | undefined }) {
  const pct = Math.round(progress * 100);
  const stage: Stage = !analysis ? "reading" : analysis.status === "done" ? "done" : analysis.status === "queued" ? "removed" : "analysing";
  const r: Redaction = analysis?.redaction ?? {};
  const secrets = Object.entries(r.secrets ?? {}).filter(([, v]) => v > 0);
  const state = (s: Stage): "waiting" | "active" | "done" => {
    const order: Stage[] = ["reading", "removed", "analysing", "done"];
    const at = order.indexOf(stage);
    const i = order.indexOf(s);
    return i < at ? "done" : i === at ? "active" : "waiting";
  };
  return (
    <div className="animate-rise mx-auto max-w-lg text-left">
      <p className="truncate font-mono text-sm text-ink-3" title={file?.name}>
        {file?.name} · {bytes(file?.size)}
      </p>
      <ol className="mt-5 space-y-5">
        <Step label="Reading and removing secrets" state={state("reading")}>
          {stage === "reading" && (
            <>
              <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-paper-2" role="progressbar" aria-label="Upload progress" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                <div className="h-full rounded-full bg-primary transition-[width] duration-200 ease-out" style={{ width: `${pct}%` }} />
              </div>
              <p className="mt-1.5 text-sm text-ink-3">{pct}% uploaded. Secrets are replaced as the file streams in.</p>
            </>
          )}
        </Step>
        <Step label="Secrets removed" state={state("removed") === "active" ? "done" : state("removed")}>
          {analysis && (
            <ul className="mt-1.5 flex flex-wrap gap-x-5 gap-y-1 text-sm">
              {secrets.length === 0 && <li className="text-ink-3">No credentials found in this file.</li>}
              {secrets.map(([k, v]) => (
                <Count key={k} n={v} one={SECRET_LABELS[k]?.[0] ?? k} many={SECRET_LABELS[k]?.[1] ?? k} />
              ))}
              {(r.response_bodies_removed ?? 0) > 0 && <Count n={r.response_bodies_removed ?? 0} one="response body dropped" many="response bodies dropped" />}
            </ul>
          )}
        </Step>
        <Step label="Finding the failing request" state={stage === "done" ? "done" : analysis ? "active" : "waiting"}>
          {analysis && stage !== "done" && <p className="mt-1 text-sm text-ink-3">Running the rules on the redacted copy…</p>}
          {stage === "done" && <p className="animate-fade mt-1 text-sm text-ink-3">Opening the result…</p>}
        </Step>
      </ol>
    </div>
  );
}

export function UploadPage() {
  const { canEdit } = useAuth();
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [analysisId, setAnalysisId] = useState<string | null>(null);

  const status = useQuery({
    queryKey: ["analysis", analysisId],
    queryFn: () => api<Analysis>(`/v1/analyses/${analysisId}`),
    enabled: analysisId !== null,
    refetchInterval: (q) => (q.state.data && ["done", "failed"].includes(q.state.data.status) ? false : 700),
  });
  const doneId = status.data?.status === "done" ? status.data.id : null;
  useEffect(() => {
    if (!doneId) return;
    // A moment to see what was removed, then the answer (no wait under reduced motion).
    const timer = window.setTimeout(() => navigate(`/analyses/${doneId}`), reducedMotion() ? 0 : 900);
    return () => window.clearTimeout(timer);
  }, [doneId, navigate]);

  async function start(chosen: File) {
    setFile(chosen);
    setError(null);
    setAnalysisId(null);
    if (chosen.size > MAX_BYTES) {
      // Checked here first: there is no point uploading 100 MB only to be refused.
      setError(new Error(`${chosen.name} is ${bytes(chosen.size)}; the limit is 100 MB. Ask the customer to record a shorter session, or use the CLI.`));
      return;
    }
    setProgress(0);
    try {
      const result = await uploadFile(chosen, setProgress);
      setAnalysisId(result.analysis_id);
    } catch (e) {
      setError(e);
      setProgress(null);
    }
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    const dropped = event.dataTransfer.files[0];
    if (dropped) void start(dropped);
  }

  const failed = status.data?.status === "failed";
  const busy = progress !== null && !error && !failed;

  return (
    <div>
      <PageHeader
        title="Analyse a HAR file"
        description="Drop the file a customer sent. Secrets come out while it uploads; then you get the failing request, the likely cause and a summary to paste into the ticket."
      />
      {!canEdit && <div className="animate-slide-down mb-6 rounded-[6px] bg-medium/15 px-4 py-3 text-sm">Viewers can read analyses but not upload files.</div>}

      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (canEdit) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={canEdit ? onDrop : (e) => e.preventDefault()}
        className={cx(
          "rounded-[12px] border-2 border-dashed px-6 py-14 text-center transition-[border-color,background-color,transform] duration-200 ease-out sm:py-20",
          dragging ? "scale-[1.01] border-primary bg-signal-soft" : "border-rule-2 bg-card",
        )}
      >
        {busy ? (
          <Progress file={file} progress={progress ?? 0} analysis={status.data} />
        ) : (
          <div className="animate-rise">
            <p className="font-display text-2xl font-medium">{dragging ? "Drop it to start" : "Drop the HAR file here"}</p>
            <p className="mt-2 text-sm text-ink-3">.har, .har.gz, or a zip with one HAR inside. Up to 100 MB and 50,000 requests.</p>
            <Button className="mt-6" variant="primary" disabled={!canEdit} onClick={() => input.current?.click()}>
              Choose a file
            </Button>
            <input
              ref={input}
              type="file"
              accept={ACCEPT}
              className="hidden"
              data-testid="file-input"
              onChange={(e) => {
                const chosen = e.target.files?.[0];
                e.target.value = ""; // choosing the same file again should start again
                if (chosen) void start(chosen);
              }}
            />
          </div>
        )}
      </div>
      {error !== null && (
        <div className="mt-4">
          <ErrorState error={error} />
        </div>
      )}
      {failed && (
        <div className="mt-4">
          <ErrorState error={new Error(status.data?.error ?? "The analysis failed.")} />
        </div>
      )}

      <div className="mt-12 grid gap-10 text-sm text-ink-2 md:grid-cols-2">
        <section className="animate-rise" style={{ animationDelay: "80ms" }}>
          <h2 className="font-display text-xl font-medium text-ink">What happens to the file</h2>
          <p className="mt-3">
            Secrets are replaced with markers like <mark className="redaction">3f9a01c2</mark> before anything is written. The same secret always gets the same
            marker, so you can still follow it from request to request.
          </p>
          <p className="mt-3">Response bodies are dropped, except small JSON error messages. Only the redacted copy is stored, encrypted, and it is deleted when it expires. Nothing is sent to any AI service.</p>
        </section>
        <section className="animate-rise" style={{ animationDelay: "160ms" }}>
          <h2 className="font-display text-xl font-medium text-ink">Prefer not to upload?</h2>
          <p className="mt-3">The same analysis runs offline on your machine:</p>
          <pre className="mt-3 overflow-x-auto rounded-[8px] bg-[#111318] p-4 font-mono text-xs leading-relaxed text-[#e6e1d3]">
            <span className="text-[#8a93a0]">$</span> hartriage analyze file.har{"\n"}
            <span className="text-[#8a93a0]">$</span> hartriage redact file.har -o clean.har
          </pre>
          <p className="mt-3">
            Customer asking how to record one? Send them{" "}
            <Link className="font-bold text-signal hover:underline" to="/kb/recording-a-har">
              recording a useful HAR file
            </Link>
            .
          </p>
        </section>
      </div>
    </div>
  );
}
