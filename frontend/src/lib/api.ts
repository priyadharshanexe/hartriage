/**
 * The one place that talks to the HAR Triage API.
 *
 * - The access token lives in memory only (never in localStorage, where any
 *   script on the page could read it). The refresh token is an HttpOnly cookie
 *   the browser sends to /v1/auth by itself.
 * - A 401 triggers one silent refresh and one retry. Requests that fail at the
 *   same moment share the same refresh, because each refresh token works once.
 * - Every failure becomes an ApiError with the API's error code, message and
 *   request id.
 */

import type { Session } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details: unknown = null,
    readonly requestId: string | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

let accessToken: string | null = null;
let onSession: ((session: Session | null) => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

/** The auth provider listens here, so a refresh anywhere updates the session. */
export function onSessionChange(listener: ((session: Session | null) => void) | null): void {
  onSession = listener;
}

export async function toApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("X-Request-Id");
  try {
    const body = (await response.json()) as {
      error?: { code?: string; message?: string; details?: unknown; request_id?: string | null };
    };
    const error = body.error ?? {};
    return new ApiError(
      response.status,
      error.code ?? "unknown_error",
      error.message ?? "Something went wrong.",
      error.details ?? null,
      error.request_id ?? requestId,
    );
  } catch {
    return new ApiError(response.status, "unknown_error", "The server sent an unexpected response.", null, requestId);
  }
}

let refreshInFlight: Promise<Session | null> | null = null;

export function refreshSession(): Promise<Session | null> {
  refreshInFlight ??= fetch("/v1/auth/refresh", { method: "POST", credentials: "same-origin" })
    .then(async (response) => {
      if (!response.ok) return null;
      const session = (await response.json()) as Session;
      setAccessToken(session.access_token ?? null);
      onSession?.(session);
      return session;
    })
    .catch(() => null)
    .finally(() => {
      refreshInFlight = null;
    });
  return refreshInFlight;
}

export interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  skipRefresh?: boolean;
  /** Return the raw text instead of parsing JSON (exports, KB articles). */
  text?: boolean;
}

export function buildUrl(path: string, query: RequestOptions["query"]): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== null && value !== undefined && value !== "") params.set(key, String(value));
  }
  const suffix = params.toString();
  return suffix ? `${path}?${suffix}` : path;
}

async function send(path: string, options: RequestOptions): Promise<Response> {
  const headers: Record<string, string> = { Accept: options.text ? "text/plain, text/markdown, */*" : "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
  try {
    return await fetch(buildUrl(path, options.query), {
      method: options.method ?? "GET",
      credentials: "same-origin",
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the server. Check your connection.");
  }
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  let response = await send(path, options);
  if (response.status === 401 && !options.skipRefresh) {
    const session = await refreshSession();
    if (session) response = await send(path, options);
    else onSession?.(null);
  }
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  if (options.text) return (await response.text()) as T;
  return (await response.json()) as T;
}

export interface UploadResult {
  analysis_id: string;
  status: string;
}

/** Upload with progress events. fetch() cannot report upload progress; XHR can. */
export function uploadFile(file: File, onProgress: (fraction: number) => void): Promise<UploadResult> {
  const attempt = () =>
    new Promise<{ status: number; body: string; requestId: string | null }>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", buildUrl("/v1/uploads", { filename: file.name }));
      if (accessToken) xhr.setRequestHeader("Authorization", `Bearer ${accessToken}`);
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(event.loaded / event.total);
      };
      xhr.onload = () => resolve({ status: xhr.status, body: xhr.responseText, requestId: xhr.getResponseHeader("X-Request-Id") });
      xhr.onerror = () => reject(new ApiError(0, "network_error", "The upload was interrupted. Check your connection."));
      xhr.send(file);
    });
  return (async () => {
    let result = await attempt();
    if (result.status === 401 && (await refreshSession())) result = await attempt();
    if (result.status >= 200 && result.status < 300) return JSON.parse(result.body) as UploadResult;
    const response = new Response(result.body, { status: result.status, headers: result.requestId ? { "X-Request-Id": result.requestId } : {} });
    throw await toApiError(response);
  })();
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

/** Per-field messages from a 422 validation error. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || error.code !== "validation_error") return {};
  const fields = (error.details as { fields?: { field: string; message: string }[] } | null)?.fields ?? [];
  const result: Record<string, string> = {};
  for (const { field, message } of fields) {
    if (!(field in result)) result[field] = message.replace(/^Value error, /, "");
  }
  return result;
}
