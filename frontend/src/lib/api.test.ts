import { describe, expect, it } from "vitest";
import { mockApi } from "../test/helpers";
import { ApiError, api, buildUrl, fieldErrors, setAccessToken } from "./api";

describe("api", () => {
  it("sends the access token and parses JSON", async () => {
    setAccessToken("abc");
    const calls = mockApi({ "GET /v1/analyses": { items: [] } });
    await expect(api("/v1/analyses")).resolves.toEqual({ items: [] });
    expect((calls[0]!.init.headers as Record<string, string>).Authorization).toBe("Bearer abc");
  });

  it("turns the error shape into an ApiError", async () => {
    mockApi({
      "GET /v1/x": () =>
        new Response(JSON.stringify({ error: { code: "invalid_har", message: "Not a valid HAR file.", request_id: "r1" } }), { status: 422 }),
    });
    const error = await api("/v1/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 422, code: "invalid_har", message: "Not a valid HAR file.", requestId: "r1" });
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    setAccessToken("old");
    let first = true;
    const calls = mockApi({
      "GET /v1/me": (_url: URL, init: RequestInit) => {
        const auth = (init.headers as Record<string, string>).Authorization;
        if (first) {
          first = false;
          return new Response("{}", { status: 401 });
        }
        return { auth };
      },
      "POST /v1/auth/refresh": { access_token: "new", user: {}, orgs: [], org_id: "o", role: "admin" },
    });
    await expect(api("/v1/me")).resolves.toEqual({ auth: "Bearer new" });
    expect(calls.map((c) => `${c.method} ${c.url.pathname}`)).toEqual(["GET /v1/me", "POST /v1/auth/refresh", "GET /v1/me"]);
  });

  it("builds query strings without empty values", () => {
    expect(buildUrl("/v1/a", { q: "", limit: 25, cursor: null, ok: true })).toBe("/v1/a?limit=25&ok=true");
  });

  it("maps validation errors to fields", () => {
    const error = new ApiError(422, "validation_error", "x", { fields: [{ field: "email", message: "value is not a valid email" }] });
    expect(fieldErrors(error)).toEqual({ email: "value is not a valid email" });
  });
});
