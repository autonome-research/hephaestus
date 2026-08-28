// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Start the Gate G4 world (INTERFACE.md §14, mission Gate G4).
//
// It spawns `harness/serve_fixture.py`, which materializes the committed public
// fixture, builds it, starts a **real** `heph serve --web`, and reopens the
// committed transcript's sessions. When that process has written the handshake
// file, the browser suite may run.
//
// NO SILENT DEGRADATION. Every failure here is fatal and named: a suite that
// started without a server, or without an agent runtime, would report "no
// sessions" for every transcript clause and pass by asserting nothing. If the
// world cannot be stood up, `pnpm test:e2e` fails at setup with the harness's
// own stderr, which is where the reason is.

import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { HANDSHAKE_PATH } from "./harness/world";

/** Where the harness's pid is left for `global-teardown.ts`. */
export const PID_PATH = join(process.cwd(), "test-results", "g4-harness.pid");

/** The repository root, from `web/`. */
const REPO = resolve(process.cwd(), "..");

/**
 * Materializing, building two parts and starting a sidecar is minutes on a cold
 * machine. Generous rather than tight: a timeout here reads as "the gate is
 * broken", and the honest failure is almost always slower than it is broken.
 */
const READY_TIMEOUT_MS = 600_000;

export default async function globalSetup(): Promise<void> {
  mkdirSync(dirname(HANDSHAKE_PATH), { recursive: true });
  rmSync(HANDSHAKE_PATH, { force: true });

  const harness = spawn(
    "uv",
    ["run", "python", join("web", "e2e", "harness", "serve_fixture.py"), HANDSHAKE_PATH],
    { cwd: REPO, stdio: ["ignore", "inherit", "inherit"], detached: false },
  );
  writeFileSync(PID_PATH, String(harness.pid ?? ""), "utf8");

  let exited: number | null = null;
  harness.on("exit", (code) => {
    exited = code ?? -1;
  });

  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (existsSync(HANDSHAKE_PATH)) return;
    if (exited !== null) {
      throw new Error(
        `the G4 harness exited with ${String(exited)} before the world was ready; ` +
          "its output is above",
      );
    }
    await sleep(250);
  }
  stop(harness);
  throw new Error(`the G4 harness did not become ready within ${String(READY_TIMEOUT_MS)} ms`);
}

function sleep(ms: number): Promise<void> {
  return new Promise((done) => setTimeout(done, ms));
}

function stop(harness: ChildProcess): void {
  harness.kill("SIGTERM");
}
