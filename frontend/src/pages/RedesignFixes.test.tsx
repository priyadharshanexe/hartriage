import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SESSION, mockApi, renderApp } from "../test/helpers";
import { InvitePage } from "./AuthPages";
import { HistoryPage } from "./HistoryPage";
import { TeamPage } from "./TeamPage";

const LOOKUP = { organization: "Acme Support", email: "new@example.com", role: "agent", expires_at: "2026-11-21T10:00:00Z", existing_account: false };

describe("InvitePage", () => {
  it("names the organisation, email and role before asking for a password", async () => {
    window.location.hash = "#tok123";
    mockApi({ "GET /v1/invitations/lookup": LOOKUP });
    renderApp(<InvitePage />);
    expect(await screen.findByRole("heading", { name: "Join Acme Support" })).toBeInTheDocument();
    expect(screen.getByText("agent")).toBeInTheDocument();
    expect(screen.getByDisplayValue("new@example.com")).toBeDisabled();
    expect(screen.queryByText(/You are signed in as/)).toBeNull();
  });

  it("warns when someone else is signed in", async () => {
    window.location.hash = "#tok123";
    mockApi({ "POST /v1/auth/refresh": SESSION, "GET /v1/invitations/lookup": LOOKUP });
    renderApp(<InvitePage />);
    expect(await screen.findByText(/You are signed in as/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign out first" })).toBeInTheDocument();
  });
});

describe("TeamPage", () => {
  it("does not let an admin change their own role", async () => {
    mockApi({
      "POST /v1/auth/refresh": SESSION,
      "GET /v1/members": {
        members: [
          { user_id: "u1", email: "ada@example.com", name: "Ada", role: "admin", joined_at: "2026-11-01T00:00:00Z", you: true },
          { user_id: "u2", email: "bo@example.com", name: "Bo", role: "agent", joined_at: "2026-11-02T00:00:00Z", you: false },
        ],
        invitations: [],
      },
    });
    renderApp(<TeamPage />);
    expect(await screen.findByLabelText("Role for ada@example.com")).toBeDisabled();
    expect(screen.getByLabelText("Role for bo@example.com")).toBeEnabled();
  });
});

describe("HistoryPage", () => {
  it("shows redaction markers in the likely cause as markers", async () => {
    mockApi({
      "POST /v1/auth/refresh": SESSION,
      "GET /v1/analyses": {
        items: [
          {
            id: "a1", status: "done", error: null, engine_version: "1.0.0", created_at: "2026-11-14T10:00:00Z", finished_at: "2026-11-14T10:00:02Z",
            filename: "x.har", size_bytes: 1, original_size_bytes: 1, entry_count: 1, expires_at: "2026-12-14T10:00:00Z",
            source: { kind: "upload" }, redaction: {}, stats: null, lead: "The token [REDACTED:abcdef12] had expired",
          },
        ],
        next_cursor: null,
      },
    });
    renderApp(<HistoryPage />);
    expect((await screen.findByText("abcdef12")).tagName).toBe("MARK");
    expect(screen.queryByText(/REDACTED:/)).toBeNull();
  });
});
