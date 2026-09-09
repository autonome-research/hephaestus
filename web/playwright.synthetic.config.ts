// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { defineConfig } from "@playwright/test";

// Isolated source-build browser checks: every API/WS request is intercepted by
// the fixture, and the fallback proxy is deliberately an unusable local port.
export default defineConfig({
  testDir: "./e2e/synthetic", workers: 1, retries: 0, forbidOnly: true,
  timeout: 30_000, expect: { timeout: 8_000 },
  outputDir: "/tmp/hephaestus-integration-validation/browser",
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:15273", viewport: { width: 1440, height: 900 },
    screenshot: "only-on-failure", trace: "retain-on-failure" },
  webServer: { command: "HEPH_WEB_API=http://127.0.0.1:9 pnpm dev --host 127.0.0.1 --port 15273",
    url: "http://127.0.0.1:15273", reuseExistingServer: false },
});
