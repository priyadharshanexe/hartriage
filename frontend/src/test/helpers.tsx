import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { AuthProvider } from "../auth/AuthProvider";
import type { Session } from "../lib/types";

export const SESSION: Session = {
  user: { id: "u1", email: "ada@example.com", name: "Ada" },
  org_id: "o1",
  role: "admin",
  orgs: [{ id: "o1", name: "Acme Support", role: "admin" }],
  access_token: "test-token",
};

type Handler = (url: URL, init: RequestInit) => unknown;

/** Route fetch() calls by "METHOD /path" to handlers; anything else is a 404. */
export function mockApi(routes: Record<string, Handler | unknown>) {
  const calls: { method: string; url: URL; init: RequestInit }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    const method = (init.method ?? "GET").toUpperCase();
    calls.push({ method, url, init });
    const handler = routes[`${method} ${url.pathname}`];
    if (handler === undefined) {
      return new Response(JSON.stringify({ error: { code: "not_found", message: "Not found." } }), { status: 404 });
    }
    const body = typeof handler === "function" ? (handler as Handler)(url, init) : handler;
    if (body instanceof Response) return body;
    if (typeof body === "string") return new Response(body, { status: 200 });
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

export function renderApp(ui: ReactNode, { path = "/", route = "/" }: { path?: string; route?: string } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <AuthProvider>
          <Routes>
            <Route path={path} element={ui} />
            <Route path="*" element={<p>other page</p>} />
          </Routes>
        </AuthProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
