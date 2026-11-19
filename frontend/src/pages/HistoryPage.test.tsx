import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Analysis } from "../lib/types";
import { SESSION, mockApi, renderApp } from "../test/helpers";
import { HistoryPage } from "./HistoryPage";

const LEAD =
  "The token [REDACTED:abcdef12] had expired 15 minutes before the request (exp 2026-11-14 08:09:42 UTC), so app.test rejected it with 401.";

const analysis: Analysis = {
  id: "a1", status: "done", error: null, engine_version: "1.0.0", created_at: "2026-11-14T10:00:00Z", finished_at: "2026-11-14T10:00:02Z",
  filename: "checkout-story.har", size_bytes: 1, original_size_bytes: 13686, entry_count: 7, expires_at: "2026-12-14T10:00:00Z",
  source: { kind: "upload" }, redaction: {}, stats: null, lead: LEAD,
};

describe("HistoryPage", () => {
  it("shows the whole likely cause, wrapped rather than cut, in both layouts", async () => {
    mockApi({ "POST /v1/auth/refresh": SESSION, "GET /v1/analyses": { items: [analysis], next_cursor: null } });
    renderApp(<HistoryPage />);
    const causes = await screen.findAllByTestId("likely-cause");
    expect(causes).toHaveLength(2); // the wide-screen table and the narrow-screen card
    for (const cause of causes) {
      expect(cause).toHaveClass("line-clamp-3");
      expect(cause.className).not.toMatch(/truncate|whitespace-nowrap/);
      expect(cause).toHaveTextContent("so app.test rejected it with 401.");
    }
  });

  it("gives each analysis a card with its status, size and dates on narrow screens", async () => {
    mockApi({ "POST /v1/auth/refresh": SESSION, "GET /v1/analyses": { items: [analysis], next_cursor: null } });
    renderApp(<HistoryPage />);
    const list = await screen.findByRole("list", { name: "Analyses" });
    const [card] = within(list).getAllByRole("listitem");
    expect(within(card!).getByRole("link", { name: "checkout-story.har" })).toHaveAttribute("href", "/analyses/a1");
    expect(card).toHaveTextContent("done");
    expect(card).toHaveTextContent("13 KB");
    expect(card).toHaveTextContent(/analysed .* · 7 requests · expires/);
  });
});
