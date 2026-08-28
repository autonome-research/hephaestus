// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Gate G4's transcript clauses:
//
//   G4.8   an agent session started **from the CLI** streams live into the web
//          panel — the event round trip (§2.1, §2.7);
//   G4.9   reopening loads a multi-page historical transcript through the
//          normalized snapshot API (§2.8, §8);
//   G4.10  quick-edit parent/child threading is preserved (§2.8, §7.1);
//   G4.11  the reopened transcript matches the previously archived event IDs
//          (§2.8's **historical** namespace);
//   G4.D   `data-tool-name` / `data-status` are stable and every chip carries
//          one `data-field` node per schema-required output field or reference
//          present in its result document (§7.2).
//
// THE ARCHIVE IS COMMITTED AND THIS SUITE ONLY READS IT. Nothing here records,
// re-baselines, or regenerates `tests/stage4/goldens/events/`. A drift is a
// failure, and the fix is `scripts/record_workspace_transcript.py` as its own
// change carrying the normalization change that caused it.
//
// THE RESTART HALF OF G4.11 IS A PYTEST, NOT THIS FILE. §2.8 asks that the
// identities hold "across a sidecar restart"; a browser cannot restart the
// sidecar, because the serving process owns it (§2.1). That half is
// `tests/stage4/test_g4_event_archive.py`. This file proves the archived
// identities reach the DOM, which that one cannot see.

import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { archive } from "./harness/archive";
import { api, open, route, world } from "./harness/world";

const ORCHESTRATOR = "sess-workspace-orchestrator";
const QUICK_EDIT = "sess-workspace-quickedit";
const PART = "tread";

/** `tests/stage4/goldens/events/workspace.jsonl`, from `web/`. */
const ARCHIVE_PATH = join(
  process.cwd(),
  "..",
  "tests",
  "stage4",
  "goldens",
  "events",
  "workspace.jsonl",
);

interface ArchivedEvent {
  readonly event_id: string;
  readonly session_id: string;
  readonly page: number;
  readonly seq: number;
  readonly kind: string;
  readonly tool_call_id?: string;
  readonly payload?: Record<string, unknown>;
}

function archived(): ArchivedEvent[] {
  return readFileSync(ARCHIVE_PATH, "utf8")
    .split("\n")
    .filter((line) => line !== "")
    .map((line) => JSON.parse(line) as ArchivedEvent);
}

async function openSession(page: Page, sessionId: string): Promise<void> {
  await open(page, route(PART, { s: sessionId }));
  await expect(page.locator('[data-testid="stream-panel"]')).toBeVisible();
}

/** Every `data-event-id` the transcript has rendered, in document order. */
async function renderedEventIds(page: Page): Promise<string[]> {
  return await page
    .locator('[data-testid="transcript"] [data-event-id]')
    .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-event-id") ?? ""));
}

// --------------------------------------------------------------------------
// G4.9 + G4.11 — the reopened transcript

test("reopening loads the multi-page transcript and matches the archive (G4.9, G4.11)", async ({
  page,
}, testInfo) => {
  const expected = archived().filter((row) => row.session_id === ORCHESTRATOR);
  const pages = Math.max(...expected.map((row) => row.page)) + 1;
  expect(pages, "the fixture transcript is no longer multi-page").toBeGreaterThan(1);

  await openSession(page, ORCHESTRATOR);

  // §8: "the panel renders progressively and shows a page counter — 'multi-page'
  // is a user-visible fact, not only a test fact."
  const bar = page.locator("[data-history-state]");
  await expect(bar).toHaveAttribute("data-history-state", "complete", { timeout: 120_000 });
  await expect(page.locator("[data-history-pages]")).toHaveAttribute(
    "data-history-pages",
    String(pages),
  );

  // G4.11: the archived identities, in the DOM, each exactly once. "Exactly
  // once" is load-bearing: contiguous text events group for layout, and a
  // grouping that dropped or duplicated an identity would still satisfy a
  // subset check.
  const rendered = await renderedEventIds(page);
  const counts = new Map<string, number>();
  for (const id of rendered) counts.set(id, (counts.get(id) ?? 0) + 1);
  const missing = expected.filter((row) => (counts.get(row.event_id) ?? 0) === 0);
  expect(missing.map((row) => row.event_id)).toEqual([]);
  for (const row of expected) {
    expect(counts.get(row.event_id), `${row.event_id} rendered more than once`).toBe(1);
  }

  // §2.8: the two namespaces are never merged, and the separator alone tells
  // them apart. A reopened transcript with no live suffix emits historical ids
  // only — an id carrying `#` here would mean history had been used to fill a
  // live gap, which §2.7 forbids outright.
  for (const id of rendered) expect(id).toContain("@");
  for (const id of rendered) expect(id).not.toContain("#");

  await archive(page, testInfo, "g4.9-reopened-transcript");
});

test("the reopened image is a metadata placeholder, not fabricated bytes (§7.3)", async ({
  page,
}) => {
  // History retains `{mimeType}` only. §8 calls this an honest limit of the
  // public event vocabulary; the panel renders it as a named absence, and the
  // fixture contains one so the branch is not untested.
  const image = archived().find((row) => row.kind === "image");
  expect(image, "the fixture transcript has no image event").toBeDefined();
  await openSession(page, ORCHESTRATOR);
  await expect(page.locator("[data-history-state]")).toHaveAttribute(
    "data-history-state",
    "complete",
    { timeout: 120_000 },
  );
  const placeholder = page.locator("[data-image-state]").first();
  await expect(placeholder).toHaveAttribute("data-image-state", "metadata_only");
  await expect(placeholder).toHaveAttribute("data-mime-type", "image/png");
});

// --------------------------------------------------------------------------
// G4.D — the tool chip contract, over the parsed result document

test("every chip carries its required and referenced result fields (G4.D)", async ({ page }) => {
  await openSession(page, ORCHESTRATOR);
  await expect(page.locator("[data-history-state]")).toHaveAttribute(
    "data-history-state",
    "complete",
    { timeout: 120_000 },
  );

  const rows = archived().filter((row) => row.session_id === ORCHESTRATOR);
  const results = new Map<string, ArchivedEvent>();
  for (const row of rows) {
    if (row.kind === "tool_result" && row.tool_call_id !== undefined) {
      results.set(row.tool_call_id, row);
    }
  }
  const calls = rows.filter((row) => row.kind === "tool_call" && row.tool_call_id !== undefined);
  expect(calls.length).toBeGreaterThan(0);

  let parsed = 0;
  let degraded = 0;
  for (const call of calls) {
    const callId = call.tool_call_id ?? "";
    const chip = page.locator(`[data-tool-call-id="${callId}"]`).first();
    const toolName = String((call.payload ?? {})["name"] ?? "");
    await expect(chip).toHaveAttribute("data-tool-name", toolName);

    const result = results.get(callId);
    expect(result, `no archived result for ${callId}`).toBeDefined();
    const isError = (result?.payload ?? {})["isError"];

    // §7.2's closed status set, derived only from normalized events. `isError`
    // true is `error`, false is `ok`; there is no fourth value here because the
    // archive is a completed transcript.
    await expect(chip).toHaveAttribute("data-status", isError === true ? "error" : "ok");

    const document = parseResult(String((result?.payload ?? {})["text"] ?? ""));
    const fields = await chip
      .locator("[data-field]")
      .evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-field") ?? ""));

    if (document === null) {
      // §7.2's NAMED failure mode: a non-JSON result renders plainly degraded —
      // zero `data-field` nodes and a stated reason — so the one case where the
      // predicate is vacuous is visibly a refusal rather than a pass.
      degraded += 1;
      expect(fields).toEqual([]);
      await expect(chip).toHaveAttribute("data-field-state", "unparsed");
      continue;
    }
    parsed += 1;

    const keys = new Set(Object.keys(document));
    const required = new Set(requiredOutputFields(toolName));
    const references = new Set([...keys].filter((key) => key.endsWith("_ref")));
    const shown = new Set(fields);

    // (1) Completeness, as CONTAINMENT: `F ⊇ (R ∪ references(D)) ∩ K`.
    for (const key of [...required, ...references]) {
      if (!keys.has(key)) continue;
      expect(shown.has(key), `${toolName} chip dropped present field ${key}`).toBe(true);
    }
    // (2) Groundedness: `F ⊆ K`. This is the half that kills a chip which
    // renders every schema field whether present or not — placeholder
    // fabrication, which §4.4's honesty discipline forbids.
    for (const field of shown) {
      expect(keys.has(field), `${toolName} chip names absent field ${field}`).toBe(true);
    }
  }

  // Both branches of the contract are exercised by this fixture, which is why
  // the recorded turn contains a call that genuinely failed.
  expect(parsed).toBeGreaterThan(0);
  expect(degraded).toBeGreaterThan(0);
});

// --------------------------------------------------------------------------
// G4.10 — threading

test("the quick-edit child threads under its parent in the tab list (G4.10)", async ({
  page,
}, testInfo) => {
  const thread = await api<{
    readonly nodes: readonly {
      readonly session_id: string;
      readonly parent_session_id: string | null;
      readonly kind: string | null;
      readonly depth: number;
    }[];
  }>(`/sessions/${ORCHESTRATOR}/thread`);
  const child = thread.nodes.find((node) => node.session_id === QUICK_EDIT);
  expect(child, "the fixture's quick-edit edge is missing").toBeDefined();

  await openSession(page, ORCHESTRATOR);
  const tabs = page.locator("[data-session-tab]");
  await expect(tabs.filter({ has: page.locator(":scope") })).not.toHaveCount(0);

  const parentTab = page.locator(`[data-session-tab="${ORCHESTRATOR}"]`);
  const childTab = page.locator(`[data-session-tab="${QUICK_EDIT}"]`);
  await expect(parentTab).toHaveAttribute("data-thread-depth", "0");
  await expect(childTab).toHaveAttribute("data-thread-depth", String(child?.depth ?? -1));
  await expect(childTab).toHaveAttribute("data-thread-kind", "quick_edit");

  // The child's own transcript reopens under its own identities — a nested tab
  // is a real session, not a label.
  await childTab.click();
  await expect(page.locator("[data-history-state]")).toHaveAttribute(
    "data-history-state",
    "complete",
    { timeout: 120_000 },
  );
  const childIds = new Set(await renderedEventIds(page));
  for (const row of archived().filter((r) => r.session_id === QUICK_EDIT)) {
    expect(childIds.has(row.event_id), `${row.event_id} missing from the child tab`).toBe(true);
  }

  await archive(page, testInfo, "g4.10-threading");
});

// --------------------------------------------------------------------------
// G4.8 — a CLI-started session streams live into the panel

test("a session started by `heph agent` streams live into the panel (G4.8)", async ({
  page,
}, testInfo) => {
  test.setTimeout(300_000);
  const before = new Set(
    (await api<SessionsDocument>("/sessions")).sessions.map((row) => row.session_id),
  );

  // §2.1: `heph serve --web` owns the leases, and `heph agent` finds
  // `.heph/serve.json` and attaches as a CLIENT rather than spawning a second
  // BridgeRuntime. Nothing about this invocation says "client mode"; that is the
  // handshake's whole point, and a second runtime here would take a second
  // writer on one project's locks.
  const agent = spawn(world().python, ["-m", "hephaestus.core.cli", "agent"], {
    cwd: world().project_root,
    stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env, PYTHONUNBUFFERED: "1" },
  });
  const transcript: string[] = [];
  agent.stdout.setEncoding("utf8");
  agent.stderr.setEncoding("utf8");
  agent.stdout.on("data", (chunk: string) => transcript.push(chunk));
  agent.stderr.on("data", (chunk: string) => transcript.push(chunk));

  try {
    // The new session is the one this process created; the panel is pointed at
    // it BEFORE the prompt runs, so the socket is subscribed when the first
    // event is minted. A panel attached afterwards would be reading history.
    const live = await waitFor(async () => {
      const now = await api<SessionsDocument>("/sessions");
      return now.sessions.map((row) => row.session_id).find((id) => !before.has(id)) ?? null;
    }, 120_000);
    expect(live, `heph agent created no session. Output:\n${transcript.join("")}`).toBeTruthy();

    await openSession(page, live ?? "");
    await expect(page.locator("[data-stream-state]")).toHaveAttribute(
      "data-stream-state",
      "live",
      { timeout: 60_000 },
    );

    agent.stdin.write("Run the project checks against the tread.\n");

    // The round trip: a chip minted by a run this browser did not start, carried
    // over `GET /events`, rendered with a LIVE identity. The separator is the
    // assertion that it came from the live namespace (§2.8) — a historical id
    // here would mean the panel had re-read history instead of streaming.
    const chip = page.locator('[data-testid="transcript"] [data-tool-name="run_checks"]');
    await expect(chip.first()).toBeVisible({ timeout: 180_000 });
    const eventId = await chip.first().getAttribute("data-event-id");
    expect(eventId ?? "").toContain("#");
    await expect(chip.first()).toHaveAttribute("data-surface", "live");
    await expect(chip.first()).toHaveAttribute("data-status", /running|ok/);
    await expect(chip.first()).toHaveAttribute("data-status", "ok", { timeout: 120_000 });

    // §2.7: a browser observer is NON-DURABLE and can never backpressure-cancel
    // a run. The run reaches a terminal state of its own.
    const terminal = page.locator("[data-terminal-state]").last();
    await expect(terminal).toHaveAttribute("data-terminal-state", "completed", {
      timeout: 120_000,
    });
    await expect(page.locator("[data-terminal-backpressure]")).toHaveCount(0);

    await archive(page, testInfo, "g4.8-live-stream");
  } finally {
    agent.stdin.end();
    agent.kill("SIGTERM");
  }
});

interface SessionsDocument {
  readonly sessions: readonly { readonly session_id: string }[];
}

async function waitFor<T>(probe: () => Promise<T | null>, timeoutMs: number): Promise<T | null> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await probe();
    if (value !== null) return value;
    await new Promise((done) => setTimeout(done, 500));
  }
  return null;
}

function parseResult(text: string): Record<string, unknown> | null {
  try {
    const value: unknown = JSON.parse(text);
    return typeof value === "object" && value !== null && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

/**
 * `R` — the tool's **required** output fields, read from the generated schema.
 *
 * Read from `schemas/tools/<name>.schema.json` rather than from a list in this
 * file: those schemas are generated from `contract/tools_decl.py` and
 * drift-tested in CI, so the predicate is anchored to the contract instead of to
 * a copy of it. A `oneOf` result takes the **union** over branches, which is
 * stricter than the gate asks and cannot let a required field slip through a
 * branch nobody looked at.
 */
function requiredOutputFields(tool: string): string[] {
  const path = resolve(process.cwd(), "..", "schemas", "tools", `${tool}.schema.json`);
  let schema: unknown;
  try {
    schema = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return [];
  }
  const result = (schema as { result?: unknown }).result;
  return [...collectRequired(result)];
}

function collectRequired(node: unknown): Set<string> {
  const found = new Set<string>();
  if (typeof node !== "object" || node === null) return found;
  const record = node as Record<string, unknown>;
  for (const name of Array.isArray(record["required"]) ? record["required"] : []) {
    if (typeof name === "string") found.add(name);
  }
  for (const key of ["oneOf", "anyOf", "allOf"]) {
    const branches = record[key];
    if (!Array.isArray(branches)) continue;
    for (const branch of branches) {
      for (const name of collectRequired(branch)) found.add(name);
    }
  }
  return found;
}
