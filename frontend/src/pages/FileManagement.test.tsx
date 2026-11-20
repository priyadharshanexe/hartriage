import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Analysis, Session } from "../lib/types";
import { SESSION, mockApi, renderApp } from "../test/helpers";
import { HistoryPage } from "./HistoryPage";
import { SettingsPage } from "./SettingsPage";

const file = (id: string, name: string, by: Analysis["uploaded_by"], kind: "upload" | "ticket" = "upload"): Analysis => ({
  id, status: "done", error: null, engine_version: "1.0.0", created_at: "2026-11-14T10:00:00Z", finished_at: "2026-11-14T10:00:02Z",
  filename: name, size_bytes: 1, original_size_bytes: 2048, entry_count: 3, expires_at: "2026-12-14T10:00:00Z",
  source: kind === "ticket" ? { kind: "ticket", platform: "zendesk", ticket_id: "9", ticket_url: null } : { kind: "upload" },
  redaction: {}, stats: null, lead: null, uploaded_by: by,
} as Analysis);

const ALICE = { id: "u2", name: "Alice", email: "alice@example.com" };
const AGENT: Session = { ...SESSION, user: { id: "u2", email: "alice@example.com", name: "Alice" }, role: "agent", orgs: [{ id: "o1", name: "Acme Support", role: "agent" }] };

describe("Files (History)", () => {
  it("admins see who uploaded each file, a Mine/All switch and bulk delete", async () => {
    const calls = mockApi({
      "POST /v1/auth/refresh": SESSION,
      "GET /v1/analyses": { items: [file("a1", "alice.har", ALICE), file("t1", "ticket.har", null, "ticket")], next_cursor: null },
      "POST /v1/analyses/bulk-delete": { deleted: 2 },
    });
    renderApp(<HistoryPage />);
    expect(await screen.findByRole("heading", { name: "Files" })).toBeInTheDocument();
    expect(screen.getByRole("radiogroup", { name: "Whose files" })).toBeInTheDocument();
    expect(await screen.findByRole("columnheader", { name: "Uploaded by" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Select all" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete 2 selected" }));
    fireEvent.click(within(await screen.findByRole("group", { name: /Delete 2 files/ })).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.some((c) => c.url.pathname === "/v1/analyses/bulk-delete")).toBe(true));
    await waitFor(() => expect(screen.queryAllByRole("link", { name: "alice.har" })).toHaveLength(0));
  });

  it("agents get no uploader column or switch, and can delete their own file after confirming", async () => {
    const calls = mockApi({
      "POST /v1/auth/refresh": AGENT,
      "GET /v1/analyses": { items: [file("a1", "alice.har", ALICE)], next_cursor: null },
      "DELETE /v1/analyses/a1": new Response(null, { status: 204 }),
    });
    renderApp(<HistoryPage />);
    const list = await screen.findByRole("list", { name: "Analyses" });
    expect(screen.queryByRole("radiogroup", { name: "Whose files" })).not.toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Uploaded by" })).not.toBeInTheDocument();
    fireEvent.click(within(list).getByRole("button", { name: "Delete" }));
    const ask = await screen.findByRole("group", { name: "Delete alice.har? The redacted copy and its analysis are removed now." });
    fireEvent.click(within(ask).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });
});

describe("Settings", () => {
  it("shows the limits, the usage bar and storage per member, and saves", async () => {
    const calls = mockApi({
      "POST /v1/auth/refresh": SESSION,
      "GET /v1/org/settings": {
        retention_days: 30, retention_choices: [7, 30, 90], max_file_mb: null, server_max_file_mb: 200, effective_max_file_mb: 200,
        storage_quota_mb: 100, daily_uploads_per_member: null, storage_used_bytes: 50 * 1024 * 1024, uploads_today: 1,
      },
      "GET /v1/org/usage": { storage_used_bytes: 50 * 1024 * 1024, storage_quota_bytes: 100 * 1024 * 1024, members: [{ user_id: "u2", name: "Alice", email: "alice@example.com", bytes: 2048, files: 1 }] },
      "PUT /v1/org/settings": {},
    });
    renderApp(<SettingsPage />);
    expect(await screen.findByRole("meter", { name: "Storage used" })).toHaveAttribute("aria-valuenow", "50");
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "7 days" }));
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(calls.find((c) => c.method === "PUT")).toBeTruthy());
    const put = calls.find((c) => c.method === "PUT")!;
    expect(JSON.parse(String(put.init.body))).toMatchObject({ retention_days: 7, storage_quota_mb: 100, max_file_mb: null });
  });
});
