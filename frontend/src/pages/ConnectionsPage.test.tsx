import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SESSION, mockApi, renderApp } from "../test/helpers";
import { ConnectionsPage } from "./ConnectionsPage";

const CREATED = {
  id: "c1", platform: "zendesk", subdomain: "acme", auth_type: "oauth_client", replace_attachments: false,
  webhook_url: "https://hooks.example/v1/webhooks/zendesk/c1", setup_steps: [], last_webhook_at: null, last_webhook_status: null,
  created_at: "2026-11-19T10:00:00Z", secret_header: null, needs_signing_secret: true, account: "Agent Ada",
};

describe("ConnectionsPage", () => {
  it("connects Zendesk with an OAuth client and no signing secret yet", async () => {
    const calls = mockApi({
      "POST /v1/auth/refresh": SESSION,
      "GET /v1/connections": { items: [] },
      "POST /v1/connections": CREATED,
    });
    renderApp(<ConnectionsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Add a connection" }));
    expect(screen.getByLabelText("Sign in with")).toHaveValue("oauth_client");
    await userEvent.type(screen.getByLabelText("Subdomain"), "acme");
    await userEvent.type(screen.getByLabelText("OAuth client unique identifier"), "hartriage");
    await userEvent.type(screen.getByLabelText("OAuth client secret"), "s3cret");
    await userEvent.click(screen.getByRole("button", { name: "Connect" }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.pathname === "/v1/connections")).toBe(true));
    const sent = JSON.parse(String(calls.find((c) => c.method === "POST" && c.url.pathname === "/v1/connections")?.init.body));
    expect(sent).toEqual({ platform: "zendesk", subdomain: "acme", oauth_client_id: "hartriage", oauth_client_secret: "s3cret" });
  });

  it("asks for the signing secret on a connection that has none", async () => {
    mockApi({ "POST /v1/auth/refresh": SESSION, "GET /v1/connections": { items: [CREATED] } });
    renderApp(<ConnectionsPage />);
    expect(await screen.findByText("Add the webhook signing secret")).toBeInTheDocument();
    expect(screen.getByLabelText("Webhook signing secret")).toBeInTheDocument();
  });
});
