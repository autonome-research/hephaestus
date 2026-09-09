// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { readFileSync } from "node:fs";
import { expect, type Page, type Route, type WebSocketRoute } from "@playwright/test";
import type { ExecutionSnapshot, HistoryUserPrompt } from "../../src/api/sessions";

export const SID = "synthetic-session";
export const OTHER = "synthetic-other";
export const RUN = "synthetic-current-run";
export const OLD = "synthetic-older-run";
export function execution(run: string | null = null, state?: string): ExecutionSnapshot {
  return { epoch: "synthetic-epoch", version: 1, run_id: run,
    active_run_id: state ? null : run, admission_available: run === null || state !== undefined,
    terminal: state && run ? { run_id: run, terminal_id: `terminal-${run}`, state, payload: { reason: "fixture outcome" } } : null };
}
const fixture = (name: string): unknown => JSON.parse(readFileSync(`test/fixtures/${name}.json`, "utf8"));
export async function setup(page: Page, initial = execution()) {
  const faults: string[] = [];
  page.on("pageerror", error => faults.push(error.message));
  let version = 0;
  const control = {
    execution: initial, sessionsFail: false, stale: false,
    prompts: [{ turn: 0, seq: 0, run_id: OLD, text: "Recorded fixture request", outcome: { state: "completed" } }] as HistoryUserPrompt[],
    events: [
      { run_id: SID, seq: 0, turn: 0, kind: "text_delta", payload: { text: "Recorded narration stays visible." } },
      { run_id: SID, seq: 1, turn: 0, kind: "tool_call", tool_call_id: "recorded-call", payload: { name: "inspect_part", arguments: { name: "bracket" } } },
      { run_id: SID, seq: 2, turn: 0, kind: "tool_result", tool_call_id: "recorded-call", payload: { toolName: "inspect_part", text: '{"status":"ok","fixture_payload":"recorded result"}', isError: false } },
    ],
    mutations: [] as { path: string; body: unknown }[],
    pending: null as Route | null, sockets: [] as WebSocketRoute[],
    tailReads: 0, sessionReads: 0, faults,
    async frame(kind: string, payload: unknown, seq: number, run = RUN, toolCallId?: string) {
      await expect.poll(() => control.sockets.length).toBeGreaterThan(0);
      control.sockets.at(-1)!.send(JSON.stringify({ session_id: SID, run_id: run, seq, kind, payload,
        ...(toolCallId ? { tool_call_id: toolCallId } : {}) }));
    },
    async release(status = 200, body: unknown = { status: "ok", run_id: RUN, run_status: "completed", terminal: { state: "completed" } }) {
      await expect.poll(() => control.pending !== null).toBe(true);
      const pending = control.pending!;
      control.pending = null;
      await pending.fulfill({ status, json: body });
    },
  };
  await page.routeWebSocket("**/api/v1/events", socket => {
    control.sockets.push(socket);
    socket.onMessage(() => undefined);
  });
  // No request can reach a real service, even if a new component starts making writes.
  await page.route("**/api/v1/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v1", "");
    if (request.method() !== "GET") {
      control.mutations.push({ path, body: request.postDataJSON() as unknown });
      if (path.endsWith("/prompt")) { control.pending = route; return; }
      if (path.endsWith("/cancel")) {
        await route.fulfill({ json: { status: "ok", run_id: path.split("/")[2], questions_cancelled: 0 } }); return;
      }
      await route.fulfill({ status: 409, json: { status: "error", reason: "fixture_unexpected_mutation", message: "Unexpected synthetic mutation" } }); return;
    }
    if (path === "/sessions") {
      control.sessionReads++;
      if (control.sessionsFail) { await route.fulfill({ status: 503, json: { status: "error", reason: "agent_unavailable", message: "Synthetic read failure" } }); return; }
      const rows = [SID, OTHER].map(session_id => ({ session_id, profile: "orchestrator", part: null,
        parent_session_id: null, thread_state: "unlinked", readable: true, unreadable_reason: null,
        execution: session_id === SID ? { ...control.execution, version: control.stale ? 0 : ++version } : { ...execution(), version: ++version } }));
      await route.fulfill({ json: { status: "ok", sessions: rows,
        profiles: [{ profile: "orchestrator", can_delegate: true, part_scoped: false, requires_part: false }] } }); return;
    }
    if (path.endsWith("/history")) {
      const tail = url.searchParams.has("after");
      if (tail) control.tailReads++;
      await route.fulfill({ json: { status: "ok", session_id: SID, events: tail ? [] : control.events,
        user_prompts: control.prompts, cursor: null, done: true, end_cursor: "opaque-fixture-tail" } }); return;
    }
    if (path.endsWith("/thread")) {
      await route.fulfill({ json: { status: "ok", session_id: path.split("/")[2], parent_session_id: null, thread_state: "unlinked", nodes: [] } }); return;
    }
    if (path === "/project") { await route.fulfill({ json: fixture("project") }); return; }
    if (path === "/parts") { await route.fulfill({ json: fixture("parts") }); return; }
    if (path === "/providers") { await route.fulfill({ json: { status: "ok", providers: [], config_path: "/synthetic/providers.json", config_exists: true, config_malformed: false, file_mode: "0600", file_mode_private: true, credential_allowlist: [], auth_source: null, auth_source_linked: false, egress_acknowledged: [], adopted_sources: [], credential_sources: [], attach: { state: "attached", cause: null } } }); return; }
    // Explicit named absence for unrelated inspector reads, not invented CAD data.
    await route.fulfill({ status: 404, json: { status: "error", reason: "not_found", message: "Not part of this synthetic fixture" } });
  });
  await page.goto(`/#t=synthetic-local-only`);
  await page.waitForFunction(() => document.querySelector("[data-pin-mode]") !== null);
  await page.evaluate(sid => { location.hash = `#/p/bracket?s=${sid}`; }, SID);
  const strip = page.locator("[data-stream-strip]");
  if (await strip.isVisible()) await strip.focus();
  await expect(page.locator("[data-composer-input]")).toBeVisible();
  return control;
}
export const input = (page: Page) => page.locator("[data-composer-input]");
export const send = (page: Page) => page.locator("[data-composer-send]");
export const stop = (page: Page) => page.locator("[data-composer-cancel]");
export const status = (page: Page) => page.locator("[data-current-turn]");
