// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Stop the Gate G4 world.
//
// `serve_fixture.py` unwinds on SIGTERM: it terminates the `heph serve --web`
// child (which clears `.heph/serve.json` and releases the project's session
// leases in its own `finally`) and closes the scripted provider. A SIGKILL here
// would leave a stale serve record behind — harmless, because `owning_server`
// probes the recorded pid, but leaving one on purpose is not tidying up.

import { existsSync, readFileSync, rmSync } from "node:fs";
import { PID_PATH } from "./global-setup";

export default function globalTeardown(): void {
  if (!existsSync(PID_PATH)) return;
  const pid = Number.parseInt(readFileSync(PID_PATH, "utf8").trim(), 10);
  rmSync(PID_PATH, { force: true });
  if (!Number.isFinite(pid) || pid <= 0) return;
  try {
    process.kill(pid, "SIGTERM");
  } catch {
    // Already gone: the harness exits on its own if `heph serve` dies, and a
    // teardown that threw over an already-stopped process would turn a green
    // run red for no reason.
  }
}
