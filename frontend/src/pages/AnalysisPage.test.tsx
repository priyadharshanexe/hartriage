import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Analysis, EntriesPage, Finding } from "../lib/types";
import { SESSION, mockApi, renderApp } from "../test/helpers";
import { AnalysisPage } from "./AnalysisPage";

const analysis: Analysis = {
  id: "a1", status: "done", error: null, engine_version: "1.0.0", created_at: "2026-11-14T10:00:00Z", finished_at: "2026-11-14T10:00:02Z",
  filename: "checkout.har", size_bytes: 1000, original_size_bytes: 2000, entry_count: 2, expires_at: "2026-12-14T10:00:00Z",
  source: { kind: "upload" }, stats: null, lead: "The token expired",
  redaction: { sentence: "Removed 1 token (3 places in 2 requests).", secrets: { tokens: 1 }, response_bodies_removed: 1 },
  summary: {
    activity: ["2 requests"], first_failure: "Request #2: GET https://api.example.com/me → 401", likely_cause: "The token [REDACTED:aaaaaaaa] had expired.",
    evidence: ["Requests #2"], next_step: "Sign in again.", kb_title: "R002: 401 Unauthorized", kb_url: "https://example.com/kb/R002-auth.md",
    redaction: "Removed 1 token.", other_findings: [], notes: [], lead_rule: "R002", engine_version: "1.0.0",
  },
};
const findings: Finding[] = [
  { id: "f1", rule_id: "R002", severity: "high", title: "401 Unauthorized: 1 request", cause: "The token had expired.", next_step: "Sign in again.", confidence: "certain", kb: "R002-auth", entry: 2, entries: [2], evidence: {} },
];
const entries: EntriesPage = {
  items: [
    { number: 1, started_ms: 0, method: "GET", url: "https://app.example.com/", host: "app.example.com", status: 200, error: "", mime: "text/html", resource_type: "document", time_ms: 100, timings: { wait: 90, receive: 10 }, request_bytes: 0, response_bytes: 500, failed: false },
    { number: 2, started_ms: 120, method: "GET", url: "https://api.example.com/me", host: "api.example.com", status: 401, error: "", mime: "application/json", resource_type: "fetch", time_ms: 50, timings: { wait: 45 }, request_bytes: 0, response_bytes: 40, failed: true },
  ],
  next_cursor: null,
  hosts: [{ host: "app.example.com", count: 1 }, { host: "api.example.com", count: 1 }],
};
const detail = {
  number: 2,
  entry: {
    startedDateTime: "2026-11-14T10:00:00.120Z",
    request: { method: "GET", url: "https://api.example.com/me", headers: [{ name: "Authorization", value: "Bearer [REDACTED:aaaaaaaa]" }] },
    response: { status: 401, statusText: "Unauthorized", headers: [{ name: "WWW-Authenticate", value: 'Bearer error="invalid_token"' }], content: { size: 40, mimeType: "application/json", comment: "Response body removed" } },
    timings: { wait: 45 },
  },
  meta: { credentials: ["authorization:bearer"], credentials_present: true, jwts: [{ location: "header:authorization", marker: "[REDACTED:aaaaaaaa]", exp: 1_763_100_000, iat: null, nbf: null, aud: [] }], correlation_ids: { "x-request-id": "req-1" } },
};

function setup() {
  return mockApi({
    "POST /v1/auth/refresh": SESSION,
    "GET /v1/analyses/a1": analysis,
    "GET /v1/analyses/a1/findings": { items: findings },
    "GET /v1/analyses/a1/entries": entries,
    "GET /v1/analyses/a1/entries/2": detail,
    "GET /v1/analyses/a1/export": "### HAR Triage summary\n",
  });
}

describe("AnalysisPage", () => {
  it("shows the summary, the redaction report and the findings", async () => {
    setup();
    renderApp(<AnalysisPage />, { path: "/analyses/:id", route: "/analyses/a1" });
    expect(await screen.findByTestId("likely-cause")).toHaveTextContent("had expired");
    expect(screen.getByTestId("redaction-sentence")).toHaveTextContent("Removed 1 token");
    expect(await screen.findByText("401 Unauthorized: 1 request")).toBeInTheDocument();
    // The marker is displayed as a marker, never as a value.
    expect(screen.getAllByText("[REDACTED:aaaaaaaa]")[0]?.tagName).toBe("MARK");
  });

  it("copies the Markdown summary for the ticket", async () => {
    const calls = setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderApp(<AnalysisPage />, { path: "/analyses/:id", route: "/analyses/a1" });
    await userEvent.click(await screen.findByRole("button", { name: "Copy for ticket" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("### HAR Triage summary\n"));
    expect(calls.some((c) => c.url.pathname.endsWith("/export") && c.url.searchParams.get("format") === "md")).toBe(true);
  });

  it("opens a finding's requests and the request detail", async () => {
    setup();
    renderApp(<AnalysisPage />, { path: "/analyses/:id", route: "/analyses/a1" });
    await userEvent.click(await screen.findByRole("button", { name: "Show 1 request" }));
    const panel = await screen.findByRole("complementary", { name: "Request 2" });
    expect(await within(panel).findByText(/expired before this request/)).toBeInTheDocument();
    expect(within(panel).queryByText(/No credentials sent/)).toBeNull();
    expect(within(panel).getByText("req-1")).toBeInTheDocument();
  });
});
