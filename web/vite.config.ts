// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Vite build/dev configuration for the workspace client (INTERFACE.md §3).
//
// Two facts drive everything here:
//
// 1. **Bundle delivery.** §3: "built assets ship inside the wheel, served by
//    `--web` from `importlib.resources`". A wheel-embedded bundle is served from
//    whatever path the serving process mounts it at, so `base` is relative and
//    the emitted `index.html` never hard-codes an origin.
// 2. **The dev server is a convenience, not a second server.** §3: "Vite's dev
//    server is a development convenience proxying `/api` to a running
//    `heph serve --web`." It proxies rather than reimplementing anything, and
//    `ws: true` carries `GET /api/v1/events` (§2.7) through the same proxy — a
//    second transport for the socket would be a second topology, and §2.1 has
//    exactly one process owning the leases.

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

/** The loopback default `heph serve --web` binds (`http/serve.py`). */
const DEV_API_ORIGIN = process.env["HEPH_WEB_API"] ?? "http://127.0.0.1:8760";

export default defineConfig({
  base: "./",
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
    // Monaco is the single heavy dependency; a raised warning limit states that
    // it is expected rather than silencing an unexamined regression.
    chunkSizeWarningLimit: 4096,
  },
  server: {
    port: 5273,
    strictPort: true,
    proxy: {
      "/api": {
        target: DEV_API_ORIGIN,
        changeOrigin: false,
        ws: true,
      },
    },
  },
});
