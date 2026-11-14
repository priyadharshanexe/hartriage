import { useQuery } from "@tanstack/react-query";
import { type DragEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { Button, cx, ErrorState, PageHeader, Spinner } from "../components/ui";
import { api, uploadFile } from "../lib/api";
import { bytes } from "../lib/format";
import type { Analysis } from "../lib/types";

const ACCEPT = ".har,.json,.gz,.zip";
const MAX_BYTES = 100 * 1024 * 1024;

const STEPS = [
  { n: "01", title: "Redact while reading", body: "Cookies, tokens, API keys, passwords and signatures become markers before a byte is written." },
  { n: "02", title: "Run the rules", body: "Eleven checks look for expired tokens, CORS, mixed content, timeouts, oversized headers and more." },
  { n: "03", title: "Write the answer", body: "One summary: the first failing request, the likely cause, the evidence and the next step." },
];

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
    refetchInterval: (q) => (q.state.data && ["done", "failed"].includes(q.state.data.status) ? false : 800),
  });
  const doneId = status.data?.status === "done" ? status.data.id : null;
  useEffect(() => {
    if (doneId) navigate(`/analyses/${doneId}`);
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
  const pct = progress === null ? 0 : Math.round(progress * 100);

  return (
    <div>
      <PageHeader
        eyebrow="New case"
        title="Analyse a HAR file"
        description="Drop the file a customer sent. Secrets are removed while it uploads, then the analysis finds the failing request and writes a summary you can paste into the ticket."
      />
      {!canEdit && <div className="mb-6 border-l-4 border-medium bg-medium/15 px-4 py-3 text-sm">Viewers can read analyses but not upload files.</div>}

      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (canEdit) setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={canEdit ? onDrop : (e) => e.preventDefault()}
        className={cx(
          "relative border-2 border-dashed px-6 py-16 text-center transition-colors",
          dragging ? "border-signal bg-signal-soft/60" : "border-ink-4 bg-card",
        )}
      >
        {busy ? (
          <div className="mx-auto max-w-md space-y-4">
            <p className="font-mono text-sm break-words text-ink">{file?.name}</p>
            {progress !== null && progress < 1 && !analysisId ? (
              <>
                <div className="h-1.5 w-full bg-paper-2" role="progressbar" aria-label="Upload progress" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                  <div className="h-full bg-ink transition-all" style={{ width: `${pct}%` }} />
                </div>
                <p className="font-mono text-xs text-ink-3">Uploading and redacting · {pct}%</p>
              </>
            ) : (
              <p className="flex items-center justify-center gap-2 font-mono text-sm text-ink-2">
                <Spinner small />
                {analysisId ? `Analysis ${status.data?.status ?? "queued"}…` : "Redacting…"}
              </p>
            )}
          </div>
        ) : (
          <>
            <p className="font-display text-2xl font-semibold">Drop the HAR file here</p>
            <p className="mt-2 text-sm text-ink-3">
              <code className="font-mono">.har</code>, <code className="font-mono">.har.gz</code>, or a zip with one HAR inside · up to 100 MB and 50,000 requests
            </p>
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
          </>
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

      <ol className="mt-10 grid gap-px border border-rule bg-rule md:grid-cols-3">
        {STEPS.map((s) => (
          <li key={s.n} className="bg-paper p-5">
            <span className="font-mono text-xs text-signal">{s.n}</span>
            <p className="mt-1 font-display text-lg font-semibold">{s.title}</p>
            <p className="mt-1 text-sm text-ink-2">{s.body}</p>
          </li>
        ))}
      </ol>

      <div className="mt-10 grid gap-10 md:grid-cols-2">
        <section>
          <h2 className="eyebrow mb-3">What happens to the file</h2>
          <ul className="space-y-2.5 text-sm text-ink-2">
            <li className="border-l-2 border-rule-2 pl-3">
              Secrets are replaced with markers such as <mark className="redaction">3f9a01c2</mark> before anything is written. The same secret gets the same marker, so you can still follow it.
            </li>
            <li className="border-l-2 border-rule-2 pl-3">Response bodies are dropped, except small JSON error messages.</li>
            <li className="border-l-2 border-rule-2 pl-3">Only the redacted copy is stored, encrypted, and deleted automatically after the retention period.</li>
            <li className="border-l-2 border-rule-2 pl-3">Nothing is sent to any AI service.</li>
          </ul>
        </section>
        <section>
          <h2 className="eyebrow mb-3">Prefer not to upload?</h2>
          <p className="text-sm text-ink-2">The same analysis runs offline on your machine:</p>
          <pre className="mt-3 overflow-x-auto bg-ink p-4 font-mono text-xs leading-relaxed text-paper">
            <span className="text-[#8a8475]">$</span> hartriage analyze file.har{"\n"}
            <span className="text-[#8a8475]">$</span> hartriage redact file.har -o clean.har
          </pre>
          <p className="mt-3 text-sm text-ink-2">
            Customer asking how to record one? Send them{" "}
            <Link className="underline decoration-signal decoration-2 underline-offset-2 hover:text-signal" to="/kb/recording-a-har">
              recording a useful HAR file
            </Link>
            .
          </p>
        </section>
      </div>
    </div>
  );
}
