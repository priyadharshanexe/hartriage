/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the browser talks only to Vite, which forwards API calls to the
// backend: one origin, so the refresh cookie works without CORS.
const api = process.env.HARTRIAGE_API_URL ?? "http://localhost:8200";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // The CSP (default-src 'self') blocks data: URIs, so never inline fonts or images.
  build: {
    assetsInlineLimit: 0,
    // Vendor code in its own long-lived chunks; pages are split by lazy routes.
    rolldownOptions: {
      output: {
        advancedChunks: {
          groups: [
            { name: "motion", test: /node_modules[\/](motion|motion-dom|motion-utils|framer-motion)[\/]/ },
            { name: "react", test: /node_modules[\/](react|react-dom|react-router|react-router-dom|scheduler)[\/]/ },
            { name: "query", test: /node_modules[\/]@tanstack[\/]/ },
          ],
        },
      },
    },
  },
  server: {
    port: 5173,
    proxy: { "/v1": { target: api, changeOrigin: false } },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
