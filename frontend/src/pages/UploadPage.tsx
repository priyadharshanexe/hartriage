import { useQuery } from "@tanstack/react-query";
import { type DragEvent, useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { Badge, Button, Card, ErrorState, PageHeader, Spinner } from "../components/ui";
import { api, uploadFile } from "../lib/api";
import { bytes } from "../lib/format";
import type { Analysis } from "../lib/types";

const ACCEPT = ".har,.json,.gz,.zip";

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

  const busy = progress !== null && !error && status.data?.status !== "failed";

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Analyse a HAR file"
        description="Drop the file a customer sent. Secrets are removed while it uploads, then the analysis finds the failing request and writes a summary you can paste into the ticket."
      />
      {!canEdit && (
        <div className="mb-4 rounded-md bg-amber-50 px-4 py-3 text-sm text-amber-900">Viewers can read analyses but not upload files.</div>
      )}
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={canEdit ? onDrop : undefined}
        className={`rounded-xl border-2 border-dashed px-6 py-14 text-center transition-colors ${dragging ? "border-brand-500 bg-brand-50" : "border-slate-300 bg-white"}`}
      >
        {busy ? (
          <div className="space-y-3">
            <p className="text-sm font-medium text-slate-800">{file?.name}</p>
            {progress !== null && progress < 1 && !analysisId ? (
              <>
                <div className="mx-auto h-2 w-64 overflow-hidden rounded bg-slate-200" role="progressbar" aria-valuenow={Math.round(progress * 100)} aria-valuemin={0} aria-valuemax={100}>
                  <div className="h-full bg-brand-600 transition-all" style={{ width: `${Math.round(progress * 100)}%` }} />
                </div>
                <p className="text-xs text-slate-500">Uploading and redacting… {Math.round(progress * 100)}%</p>
              </>
            ) : (
              <p className="flex items-center justify-center gap-2 text-sm text-slate-600">
                <Spinner small />
                {analysisId ? `Analysis ${status.data?.status ?? "queued"}…` : "Redacting…"}
              </p>
            )}
          </div>
        ) : (
          <>
            <p className="text-sm text-slate-700">
              Drag a <code className="rounded bg-slate-100 px-1">.har</code> file here (also <code className="rounded bg-slate-100 px-1">.har.gz</code> or a zip with one HAR inside)
            </p>
            <Button className="mt-4" variant="primary" disabled={!canEdit} onClick={() => input.current?.click()}>
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
                if (chosen) void start(chosen);
              }}
            />
            <p className="mt-3 text-xs text-slate-500">Up to 100 MB and 50,000 requests.</p>
          </>
        )}
      </div>
      {error !== null && (
        <div className="mt-4">
          <ErrorState error={error} />
        </div>
      )}
      {status.data?.status === "failed" && (
        <div className="mt-4">
          <ErrorState error={new Error(status.data.error ?? "The analysis failed.")} />
        </div>
      )}

      <div className="mt-8 grid gap-4 md:grid-cols-2">
        <Card title="What happens to the file">
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-slate-600">
            <li>It is read as it uploads. Cookies, tokens, API keys, passwords and signatures are replaced with markers such as <Badge tone="amber">[REDACTED:3f9a01c2]</Badge> before anything is written.</li>
            <li>Response bodies are dropped, except small JSON error messages.</li>
            <li>Only the redacted copy is stored, encrypted, and deleted automatically after the retention period.</li>
            <li>Nothing is sent to any AI service.</li>
          </ul>
        </Card>
        <Card title="Prefer not to upload?">
          <p className="text-sm text-slate-600">The same analysis runs offline on your machine:</p>
          <pre className="mt-2 overflow-x-auto rounded bg-slate-900 p-3 text-xs text-slate-100">
            hartriage analyze file.har{"\n"}hartriage redact file.har -o clean.har
          </pre>
          <p className="mt-2 text-sm text-slate-600">
            Customers asking how to record one: <Link className="text-brand-700 underline" to="/kb/recording-a-har">recording a useful HAR file</Link>.
          </p>
        </Card>
      </div>
      {file && <p className="mt-4 text-xs text-slate-400">Selected: {file.name} ({bytes(file.size)})</p>}
    </div>
  );
}
