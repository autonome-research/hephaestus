// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Recovery gets its own disposable PACKAGED fixture, not extra budget from the
// shared G4 provider. Reuses the existing Python fixture and its unchanged limits.
import { spawn, type ChildProcess } from "node:child_process";
import { existsSync, mkdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import type { Page } from "@playwright/test";
import type { World } from "./world";
export { route } from "./world";

let harness: ChildProcess | null = null;
let owned: World | null = null;
export function world(): World {
  if (owned === null) throw new Error("recovery world is not ready");
  return owned;
}
export async function startRecoveryWorld(output: string): Promise<void> {
  const directory = join(output, "recovery-owned");
  mkdirSync(directory, { recursive: true });
  const handshake = join(directory, "handshake.json");
  if (existsSync(handshake)) throw new Error("refusing to overwrite recovery fixture");
  const child = spawn("uv", ["run", "python", "web/e2e/harness/serve_fixture.py", handshake], {
    cwd: resolve(process.cwd(), ".."), stdio: ["ignore", "ignore", "inherit"],
  });
  harness = child;
  const until = Date.now() + 600_000; // same packaged setup bound, not a model budget
  while (!existsSync(handshake)) {
    if (child.exitCode !== null || child.signalCode !== null) throw new Error("recovery fixture exited before ready");
    if (Date.now() > until) { await closeRecoveryWorld(); throw new Error("recovery fixture setup timed out"); }
    await new Promise(resolve_ => setTimeout(resolve_, 250));
  }
  owned = JSON.parse(readFileSync(handshake, "utf8")) as World;
  if (!["127.0.0.1", "localhost", "[::1]"].includes(new URL(owned.base_url).hostname)
    || !["127.0.0.1", "localhost", "[::1]"].includes(new URL(owned.model_base_url).hostname)) {
    await closeRecoveryWorld(); throw new Error("recovery fixture is not loopback-only");
  }
}
export async function closeRecoveryWorld(): Promise<void> {
  const child = harness;
  harness = null;
  if (child === null || child.exitCode !== null || child.signalCode !== null) return;
  await new Promise<void>(resolve_ => {
    child.once("exit", () => resolve_());
    child.kill("SIGTERM"); // exact ChildProcess created above; Python owns child cleanup
  });
}
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const w = world();
  const response = await fetch(`${w.base_url}/api/v1${path}`, { ...init,
    headers: { ...init.headers, Authorization: `Bearer ${w.token}`, Connection: "close" } });
  if (!response.ok) throw new Error(`recovery ${path}: ${response.status}`);
  return await response.json() as T;
}
export async function open(page: Page, hash: string): Promise<void> {
  const w = world();
  await page.goto(`${w.base_url}/#t=${w.token}`);
  await page.waitForFunction(() => document.querySelector("[data-pin-mode]") !== null);
  await page.evaluate(next => { window.location.hash = next; }, hash);
  await page.waitForFunction(expected => window.location.hash.startsWith(expected), hash.split("?")[0]!);
}
