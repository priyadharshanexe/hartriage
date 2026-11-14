import { describe, expect, it } from "vitest";
import { applyFilter } from "../components/Waterfall";
import type { EntryRow } from "./types";
import { bytes, epoch, ms, phaseDurations, splitMarkers, statusTone } from "./format";

describe("format", () => {
  it("formats sizes and durations", () => {
    expect(bytes(0)).toBe("—");
    expect(bytes(2048)).toBe("2 KB");
    expect(bytes(3 * 1024 * 1024)).toBe("3.0 MB");
    expect(ms(850)).toBe("850 ms");
    expect(ms(3500)).toBe("3.50 s");
    expect(epoch(0)).toBe("1970-01-01 00:00:00 UTC");
  });

  it("separates TLS from connect", () => {
    expect(phaseDurations({ connect: 120, ssl: 80, wait: 50, dns: -1 })).toEqual({ connect: 40, ssl: 80, wait: 50 });
  });

  it("splits redaction markers out of text", () => {
    expect(splitMarkers("Bearer [REDACTED:3f9a01c2] ok")).toEqual([
      { text: "Bearer ", marker: false },
      { text: "[REDACTED:3f9a01c2]", marker: true },
      { text: " ok", marker: false },
    ]);
  });

  it("colours statuses", () => {
    expect(statusTone(200, "")).toBe("green");
    expect(statusTone(404, "")).toBe("amber");
    expect(statusTone(0, "net::ERR_FAILED")).toBe("red");
  });
});

const row = (n: number, extra: Partial<EntryRow>): EntryRow => ({
  number: n, started_ms: n * 10, method: "GET", url: `https://a.com/${n}`, host: "a.com", status: 200, error: "",
  mime: "", resource_type: "", time_ms: 100, timings: {}, request_bytes: 0, response_bytes: 0, failed: false, ...extra,
});

describe("waterfall filter", () => {
  const rows = [row(1, {}), row(2, { status: 500, failed: true }), row(3, { host: "b.com", time_ms: 5000 })];
  const none = { failedOnly: false, host: "", minMs: null, text: "", numbers: null };
  it("filters by failure, host, time, text and numbers", () => {
    expect(applyFilter(rows, { ...none, failedOnly: true }).map((r) => r.number)).toEqual([2]);
    expect(applyFilter(rows, { ...none, host: "b.com" }).map((r) => r.number)).toEqual([3]);
    expect(applyFilter(rows, { ...none, minMs: 1000 }).map((r) => r.number)).toEqual([3]);
    expect(applyFilter(rows, { ...none, text: "500" }).map((r) => r.number)).toEqual([2]);
    expect(applyFilter(rows, { ...none, numbers: new Set([1, 3]) }).map((r) => r.number)).toEqual([1, 3]);
  });
});
