// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Playwright configuration for `pnpm test:e2e` — the literal G4 gate command
// (mission_plan.md Stage 4; INTERFACE.md §3, §16 row G4.0).
//
// The suite runs against a **real** `heph serve --web` on the public workspace
// fixture, stood up by `e2e/global-setup.ts` (which drives
// `e2e/harness/serve_fixture.py`) and stopped by `e2e/global-teardown.ts`.
// There is no `webServer` block and no dev-server proxy: since `serve --web`
// serves the built bundle itself (`http/serve.py::with_bundle`), the browser
// loads the app from the same origin that serves the API, which is the
// topology a wheel-installed operator gets.
//
// What this file settles, because these are configuration decisions:
//
// * **G4.12, "screenshot artifacts archived".** `outputDir` is the archive.
//   Failures retain a screenshot and a trace automatically; the specs
//   additionally attach named screenshots at the moments the gate is about.
//   §16's row says it in as many words: screenshots are **never** an assertion.
// * **One browser.** §3's posture is loopback plus a bearer token on one
//   machine; a cross-browser matrix would multiply gate time for a workspace
//   that ships as a wheel-embedded bundle opened by its own operator.
// * **Determinism.** No retries: a flaky assertion that passes on retry is a
//   flaky assertion, and `verification.md` Tier 2 wants a decision, not a coin.
// * **Serial.** One project, one server, one set of session leases (§2.1). Two
//   workers would be two operators on one workspace.
// * **No `--pass-with-no-tests` escape.** A gate command that reports success
//   while containing no assertions is the degenerate pass mission rule 1
//   requires be closed.

import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: true,
  retries: 0,
  // Building a GLB, rendering a section plate and running a DFM pack are real
  // engine work behind these assertions; the default 30 s is a timeout on the
  // engine, not on the browser.
  timeout: 180_000,
  expect: { timeout: 30_000 },
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  outputDir: "test-results",
  use: {
    ...devices["Desktop Chrome"],
    // §4.1's breakpoints are part of the layout contract; the gate runs above
    // both of them, where the Rail, Stage and Stream are all present.
    viewport: { width: 1600, height: 1000 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
