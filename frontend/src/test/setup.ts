import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage.clear();
});

// jsdom has no layout, so it has no scrolling either.
Element.prototype.scrollIntoView ??= function scrollIntoView() {};
