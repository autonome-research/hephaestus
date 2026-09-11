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

/**
 * Every event id the transcript has rendered, in document order.
 *
 * Approved conversation-first rendering gives every tool call its own row.
 * The legacy plural attribute is still read so this identity assertion remains
 * strict across any archived row shape: no layout grouping may lose an id.
 */
async function renderedEventIds(page: Page): Promise<string[]> {
  return await page
    .locator('[data-testid="transcript"] [data-event-id], [data-testid="transcript"] [data-event-ids]')
    .evaluateAll((nodes) =>
      nodes.flatMap((node) => {
        const ids = new Set<string>();
        const single = node.getAttribute("data-event-id");
        if (single !== null && single !== "") ids.add(single);
        for (const id of (node.getAttribute("data-event-ids") ?? "").split(" ")) {
          if (id !== "") ids.add(id);
        }
        return [...ids];
      }),
    );
}

/** The chip rendering one tool call (legacy grouped attributes included). */
function chipForCall(page: Page, callId: string) {
  return page
    .locator(`[data-tool-call-id="${callId}"], [data-tool-call-ids~="${callId}"]`)
    .first();
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

  // §8(c), amended 2026-09-01: multi-page is still a user-visible fact and the
  // gate still reads it by name — from the panel ROOT, which carries
  // `data-history-state` and `data-history-pages` unconditionally now that the
  // drawn counter is exception-only.
  const panel = page.locator('[data-testid="stream-panel"]');
  await expect(panel).toHaveAttribute("data-history-state", "complete", { timeout: 120_000 });
  await expect(panel).toHaveAttribute("data-history-pages", String(pages));
  await expect(page.locator("[data-history-state]")).toHaveCount(1);

  // §8(b)'s negative half, over the exact case it names: "a multi-page history
  // whose latest page is the one on screen". The count is in the DOM as an
  // attribute and nowhere as a row.
  await expect(page.locator("[data-history-bar]")).toHaveCount(0);
  await expect(page.getByText("pages of recorded transcript")).toHaveCount(0);

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

  // §7.3 C2/C21 + §8 C3 (amended 2026-09-03): no presentation row is ever
  // reconstructed on reopen — the echo is one tab's memory of one send, and a
  // reopened transcript's run structure is the ordinal namespace, which has no
  // runs to mark. Named-absence hedges left the well: operator turns restore
  // from history's `user_prompts`, and a finished turn looks finished.
  await expect(page.locator('[data-row="local-prompt"]')).toHaveCount(0);
  await expect(page.locator('[data-row="run-start"]')).toHaveCount(0);
  await expect(page.locator('[data-absence="user_prompt"]')).toHaveCount(0);
  await expect(page.locator('[data-absence="terminal"]')).toHaveCount(0);
  await expect(page.locator("body")).not.toContainText(
    "This reopened transcript doesn't show how the run ended.",
  );
  await expect(page.locator('[data-testid="transcript"] [data-markdown]').first()).toBeVisible();

  const sessionBefore = page.url();
  expect(sessionBefore).toContain(`s=${ORCHESTRATOR}`);
  await page.reload();
  await expect(page.locator('[data-testid="stream-panel"]')).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('[data-testid="stream-panel"]')).toHaveAttribute(
    "data-history-state",
    "complete",
    { timeout: 120_000 },
  );
  expect(page.url()).toContain(`s=${ORCHESTRATOR}`);
  await expect(page.locator(`[data-session-tab="${ORCHESTRATOR}"]`)).toHaveCount(1);
  await expect(page.locator("body")).not.toContainText(
    "This reopened transcript doesn't show how the run ended.",
  );

  // G4.11's amended matcher rule, both ways: the by-name skip covers exactly
  // the two presentation rows plus §8's honesty rows — any OTHER `data-row`
  // element that carries no event id (itself or within) is a mismatch.
  const idlessRows = await page
    .locator('[data-testid="transcript"] [data-row]')
    .evaluateAll((nodes) =>
      nodes
        .filter(
          (node) =>
            !node.hasAttribute("data-event-id") &&
            node.querySelector("[data-event-id], [data-event-ids]") === null,
        )
        .map((node) => node.getAttribute("data-row") ?? ""),
    );
  for (const name of idlessRows) {
    expect(["local-prompt", "run-start", "absence", "seam", "resync", "turn-outcome"]).toContain(
      name,
    );
  }

  // Horizontal Latest is outside the scroller, never over visible evidence.
  // Both mount conditions, clipping-aware pairwise clearance and true bottom.
  await expect(page.locator("[data-jump-latest]")).toHaveCount(0); // followed: never mounted
  await page.locator("[data-transcript-scroll]").evaluate((node) => {
    node.scrollTop = 0; // leave the newest row: following stops
  });
  const pill = page.locator("[data-jump-latest]");
  await expect(pill).toHaveCount(1);
  const pillBox = await pill.boundingBox();
  expect(pillBox).not.toBeNull();
  const scroller = page.locator("[data-transcript-scroll]");
  const clip = (await scroller.boundingBox())!;
  expect(pillBox!.y).toBeGreaterThanOrEqual(clip.y + clip.height);
  expect(await pill.evaluate(el => el.closest("[data-transcript-scroll]") === null)).toBe(true);
  expect(await pill.evaluate(el => getComputedStyle(el).writingMode)).toBe("horizontal-tb");
  const cardBoxes = await page
    .locator("[data-tool-name], [data-row]")
    .evaluateAll((nodes, clip) =>
      nodes.map((node) => {
        const box = node.getBoundingClientRect();
        const x = Math.max(box.x, clip.x), y = Math.max(box.y, clip.y);
        return { x, y, width: Math.min(box.right, clip.x + clip.width) - x,
          height: Math.min(box.bottom, clip.y + clip.height) - y };
      }).filter(box => box.width > 0 && box.height > 0), clip,
    );
  expect(cardBoxes.length).toBeGreaterThan(0);
  for (const box of cardBoxes) {
    const disjoint =
      (pillBox?.x ?? 0) >= box.x + box.width ||
      (pillBox?.x ?? 0) + (pillBox?.width ?? 0) <= box.x ||
      (pillBox?.y ?? 0) >= box.y + box.height ||
      (pillBox?.y ?? 0) + (pillBox?.height ?? 0) <= box.y;
    expect(disjoint, "the Latest pill overlaps a transcript row").toBe(true);
  }
  await pill.click();
  await expect(page.locator("[data-jump-latest]")).toHaveCount(0); // following again
  await expect.poll(() => scroller.evaluate(el => el.scrollHeight - el.clientHeight - el.scrollTop)).toBeLessThan(4);

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
    const toolName = String((call.payload ?? {})["name"] ?? "");
    // Approved conversation-first rendering gives every call an independently
    // expandable chip, so its schema contract is asserted on that call's chip.
    const chip = chipForCall(page, callId);
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
// Approved conversation-first semantics — one independently expandable tool
// row per call. Repetition never hides narration or changes event identity.

test("repeated calls remain individual collapsed tools and keep every identity (§7)", async ({
  page,
}) => {
  const rows = archived().filter((row) => row.session_id === ORCHESTRATOR);
  const callsByTool = new Map<string, ArchivedEvent[]>();
  for (const row of rows) {
    if (row.kind !== "tool_call") continue;
    const name = String((row.payload ?? {})["name"] ?? "");
    callsByTool.set(name, [...(callsByTool.get(name) ?? []), row]);
  }
  const [tool, calls] = [...callsByTool.entries()].sort((a, b) => b[1].length - a[1].length)[0] ?? [
    "",
    [],
  ];
  expect(calls.length, "the fixture transcript no longer repeats any call").toBeGreaterThan(1);

  await openSession(page, ORCHESTRATOR);
  await expect(page.locator("[data-history-state]")).toHaveAttribute(
    "data-history-state",
    "complete",
    { timeout: 120_000 },
  );

  const chips = page.locator(`[data-tool-name="${tool}"]`);
  await expect(chips).toHaveCount(calls.length);
  await expect(page.locator("[data-chip-repeat], [data-cycle-line]")).toHaveCount(0);

  const callIds = calls.map((call) => call.tool_call_id ?? "");
  const drawn = await chips.evaluateAll((nodes) =>
    nodes.map((node) => ({
      callId: node.getAttribute("data-tool-call-id"),
      open: node.querySelector("[data-chip-detail]")?.hasAttribute("open") ?? false,
    })),
  );
  expect(drawn.map((chip) => chip.callId)).toEqual(callIds);
  expect(drawn.every((chip) => !chip.open), "a tool disclosure opened by default").toBe(true);
  for (const callId of callIds) {
    await expect(page.locator(`[data-tool-call-id="${callId}"]`)).toHaveCount(1);
  }

  // Details remain mounted for identity/schema coverage but hidden until this
  // call's own native disclosure opens. Opening one must not open its peers.
  const first = chips.first();
  await expect(first.locator("[data-field]").first()).toBeHidden();
  await expect(page.locator("[data-chip-detail-count]")).toHaveCount(0);
  await first.locator("[data-chip-detail] > summary").click();
  await expect(first.locator("[data-chip-detail]")).toHaveAttribute("open", "");
  await expect(first.locator("[data-field]").first()).toBeVisible();
  await expect(page.locator("[data-chip-detail][open]")).toHaveCount(1);
  await expect(page.locator("[data-chip-detail-count]")).toHaveCount(1);

  // Successful tools stay quiet at rest; failure handling is covered by the
  // schema/status test above and remains per-call rather than grouped.
  const notes = await chips.evaluateAll((nodes) =>
    nodes.map((node) => node.textContent ?? "").filter((text) => text.includes("No result for")),
  );
  expect(notes).toEqual([]);
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
  // The compact header draws only the selected tab. The full server-shaped
  // forest lives in the session dropdown, where depth/kind remain inspectable.
  const parentTab = page.locator(`[data-session-tab="${ORCHESTRATOR}"]`);
  await expect(parentTab).toHaveAttribute("data-thread-depth", "0");
  await page.locator("[data-session-switch]").click();
  const childOption = page.locator(`[data-session-option="${QUICK_EDIT}"]`);
  await expect(childOption).toHaveAttribute("data-thread-depth", String(child?.depth ?? -1));
  await expect(childOption).toHaveAttribute("data-thread-kind", "quick_edit");

  // The child's own transcript reopens under its own identities — a dropdown
  // option addresses a real session, not merely a label.
  await childOption.click();
  await expect(page.locator(`[data-session-tab="${QUICK_EDIT}"]`)).toHaveCount(1);
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
// Approved compact session header: selected title at rest, full forest in a
// dropdown, and diagnostics behind a secondary disclosure.

test("the compact session header switches through the session dropdown (§7.1)", async ({
  page,
}) => {
  await openSession(page, ORCHESTRATOR);
  const column = page.locator("aside");
  await expect(page.locator("[data-session-tab]").first()).toBeVisible();

  // §7.1(a): the heading does not render in any state, and the list keeps the
  // same string as its accessible name.
  await expect(column.getByRole("heading")).toHaveCount(0);
  await expect(column.getByText("Sessions", { exact: true })).toHaveCount(0);
  await expect(column.locator("[role='tablist']")).toHaveAttribute("aria-label", "Sessions");
  await expect(page.locator("[data-session-tab]")).toHaveCount(1);
  await expect(page.locator(`[data-session-tab="${ORCHESTRATOR}"]`)).toHaveCount(1);

  // The full session forest is a dropdown, not a row of tabs. It retains every
  // session's identity and thread metadata, and explicit selection closes the
  // switcher and restores focus to its stable trigger.
  const sessionSwitch = page.locator("[data-session-switch]");
  await expect(sessionSwitch).toHaveAttribute("aria-expanded", "false");
  await sessionSwitch.click();
  const switcher = page.locator("[data-session-switch-open]");
  await expect(switcher).toHaveCount(1);
  const listing = await api<SessionsDocument>("/sessions");
  await expect(switcher.locator("[data-session-option]")).toHaveCount(listing.sessions.length);
  for (const row of listing.sessions) {
    await expect(switcher.locator(`[data-session-option="${row.session_id}"]`)).toHaveCount(1);
  }
  const optionNames = await switcher
    .locator("[data-session-option]")
    .evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("aria-label") ?? node.textContent ?? ""),
    );
  for (const name of optionNames) {
    expect(name).not.toBe("");
    expect(name).not.toBe("New conversation");
    expect(name).not.toBe("Start a session");
    expect(name).not.toMatch(/^Ask about /);
  }
  await switcher.locator(`[data-session-option="${ORCHESTRATOR}"]`).click();
  await expect(switcher).toHaveCount(0);
  await expect(sessionSwitch).toBeFocused();

  // §7.1(b): one compact create in the strip, and neither wording drawn as a
  // visible button label while the strip is drawn. The menu is drawn only while
  // open, so both entries are absent until the `+` is pressed.
  const create = page.locator("[data-session-create], [data-session-create-menu]");
  await expect(create).toHaveCount(1);
  // The worded pair is not drawn beside the strip in any form: every worded
  // create action carries `data-create-profile`, and none is mounted. (§7.1
  // C6, amended 2026-09-02: a session tab may no longer read "New session"
  // either — no tab's accessible name is string-equal to a create-control
  // label, asserted below.)
  await expect(page.locator("[data-create-profile]")).toHaveCount(0);
  await expect(page.locator("[data-session-create-open]")).toHaveCount(0);
  // A part is selected here (the route names one), so the `+` has two entries
  // and opens a menu. The one-entry case activates directly and is not pressed
  // from an e2e: `POST /sessions` is at-least-once and there is no route that
  // closes a session, so a click here would leave one behind (§7A.2).
  const menuButton = page.locator("[data-session-create-menu]");
  await expect(menuButton).toHaveCount(1);
  await expect(menuButton).toHaveAttribute("aria-expanded", "false");
  await menuButton.click();
  const menu = page.locator("[data-session-create-open]");
  await expect(menu).toHaveCount(1);
  await expect(menu.locator("[data-session-create]")).toHaveCount(1);
  await expect(menu.locator("[data-session-ask]")).toHaveCount(1);
  await expect(menu.getByText("New conversation", { exact: true })).toHaveCount(1);
  await expect(menu.getByText(`Ask about ${PART}`, { exact: true })).toHaveCount(1);
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);

  // §3.9 C29: the `+` is a quiet button with a worded accessible name, never a
  // bare accent glyph.
  await expect(create).toHaveAttribute("data-variant", "quiet");
  await expect(create).toHaveAccessibleName("New conversation");
  await expect(create.locator('span[aria-hidden="true"]')).toHaveText("New");

  // §4.1(h), amended 2026-09-02 (C25): the eyebrow band is struck as a band.
  // The collapse control is a descendant of the session tab strip and its last
  // interactive element; the column's name stays on the `aside`.
  const collapse = page.locator("[data-stream-collapse]");
  await expect(collapse).toHaveCount(1);
  await expect(column).toHaveAttribute("aria-label", "Agent");
  const placement = await collapse.evaluate((node) => {
    const strip = node.closest("[data-session-strip]");
    if (strip === null) return null;
    const interactive = [...strip.querySelectorAll("button, a[href], [tabindex]")];
    return { last: interactive[interactive.length - 1] === node };
  });
  expect(placement).toEqual({ last: true });

  // Successful connection/history details are optional diagnostics, collapsed
  // behind one native disclosure instead of occupying a prominent status row.
  const diagnostics = page.locator('[data-testid="stream-panel"] > details').first();
  await expect(diagnostics).toHaveCount(1);
  await expect(diagnostics).not.toHaveAttribute("open", "");
  await expect(diagnostics.locator(":scope > summary")).toBeVisible();
  await expect(
    page.locator(
      '[data-testid="stream-panel"] > [data-stream-state], [data-testid="stream-panel"] > [data-history-bar]',
    ),
  ).toHaveCount(0);
  await expect(page.locator("[data-current-turn]")).toHaveCount(0);
});

// --------------------------------------------------------------------------
// J-web-stream-1 / J-web-stream-2 — the aside holds ONE child and therefore
// ONE definite row (RC-11). The shipped two-row template auto-placed that one
// child into a content-sized first row and left the second absorbing every
// leftover pixel with nothing in it, so the composer sat under the tab strip
// instead of at the column's bottom — for every session shorter than the
// column, not only an empty one. J-web-stream-2 lands with it: with the void
// closed, a session with zero turns needs its OWN composed state rather than
// an empty list, or the void reopens at 812px instead of 780px.

/** The aside/panel/composer geometry the fix makes exact, at a stable width. */
async function asideGeometry(page: Page): Promise<{
  readonly asideHeight: number;
  readonly panelHeight: number;
  readonly asideBottom: number;
  readonly composerBottom: number;
}> {
  return await page.evaluate(() => {
    const asideEl = document.querySelector("aside");
    const panel = document.querySelector('[data-testid="stream-panel"]');
    const composer = document.querySelector("[data-composer]");
    if (asideEl === null || panel === null || composer === null) {
      throw new Error("aside, stream-panel or composer not found");
    }
    const asideBox = asideEl.getBoundingClientRect();
    return {
      asideHeight: asideBox.height,
      panelHeight: panel.getBoundingClientRect().height,
      asideBottom: asideBox.bottom,
      composerBottom: composer.getBoundingClientRect().bottom,
    };
  });
}

test("the composer sits at the column's bottom edge, and the panel fills the aside (J-web-stream-1)", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await openSession(page, ORCHESTRATOR);
  await expect(page.locator('[data-testid="transcript"] [data-row]').first()).toBeVisible();

  const withTranscript = await asideGeometry(page);
  // Within a pixel: the reproduction measured a 780px void from a
  // content-sized first row; the fix makes the row the aside's own height, so
  // the panel and the aside must agree to within rounding.
  expect(
    Math.abs(withTranscript.panelHeight - withTranscript.asideHeight),
    `panel ${String(withTranscript.panelHeight)} vs aside ${String(withTranscript.asideHeight)}`,
  ).toBeLessThanOrEqual(1);
  expect(
    Math.abs(withTranscript.composerBottom - withTranscript.asideBottom),
    `composer bottom ${String(withTranscript.composerBottom)} vs aside bottom ${String(withTranscript.asideBottom)}`,
  ).toBeLessThanOrEqual(1);

  await archive(page, testInfo, "stream-aside-parity-transcript");
});

test("the composer still sits at the column's bottom edge for an EMPTY session (J-web-stream-1, J-web-stream-2)", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await open(page, route(PART));
  await expect(page.locator('[data-testid="stream-panel"]')).toBeVisible();

  const menuButton = page.locator("[data-session-create-menu]");
  if ((await menuButton.count()) > 0) await menuButton.click();
  await page.locator("[data-session-create]").first().click();
  const creation = page.getByRole("dialog", { name: "New conversation · Project", exact: true });
  await expect(creation).toContainText("Proposed default");
  await expect(creation.getByRole("button", { name: "Create conversation", exact: true })).toBeEnabled();
  await creation.getByRole("button", { name: "Create conversation", exact: true }).click();
  await expect
    .poll(async () => await page.locator("[data-session-tab][aria-selected='true']").count())
    .toBe(1);

  // J-web-stream-2's own state: a session read as complete, zero rows, no
  // sessions-empty title and no create-session string leaking into it.
  const empty = page.locator("[data-transcript-empty]");
  await expect(empty).toHaveCount(1);
  const emptyText = (await empty.textContent()) ?? "";
  expect(emptyText).not.toMatch(/new session/i);
  expect(emptyText).not.toMatch(/no sessions/i);
  // No action lives in the composed state itself — the composer below it is
  // the action (§7.1 forbids a second create affordance here).
  await expect(empty.locator("button")).toHaveCount(0);

  // The empty state occupies more than half the transcript region — the
  // assertion the ledger names as proving J-web-stream-1 and -2 landed
  // together: it needs the closed void to have somewhere to grow into.
  const region = await page.evaluate(() => {
    const host = document.querySelector("[data-transcript-empty]");
    const scroller = document.querySelector("[data-transcript-scroll]") ?? host?.parentElement ?? null;
    if (host === null || scroller === null) return null;
    return {
      empty: host.getBoundingClientRect().height,
      region: scroller.getBoundingClientRect().height,
    };
  });
  expect(region).not.toBeNull();
  if (region !== null) {
    expect(region.empty, `empty state ${String(region.empty)} vs region ${String(region.region)}`).toBeGreaterThan(
      region.region / 2,
    );
  }

  const geometry = await asideGeometry(page);
  expect(
    Math.abs(geometry.panelHeight - geometry.asideHeight),
    `panel ${String(geometry.panelHeight)} vs aside ${String(geometry.asideHeight)}`,
  ).toBeLessThanOrEqual(1);
  expect(
    Math.abs(geometry.composerBottom - geometry.asideBottom),
    `composer bottom ${String(geometry.composerBottom)} vs aside bottom ${String(geometry.asideBottom)}`,
  ).toBeLessThanOrEqual(1);

  await archive(page, testInfo, "stream-aside-parity-empty");
});

// --------------------------------------------------------------------------
// J-web-stream-3 — the general invariant: every descendant of the stream
// aside fits inside it. The composer's unavailable-provider refusal is the
// reproduction (a 621px path chip inside a 395px column), but the fix note
// itself asks for the invariant "that would catch the next one too" rather
// than a pinned pixel count for this one case.

test("every descendant of the stream aside fits inside it, at two widths (J-web-stream-3)", async ({
  page,
}, testInfo) => {
  for (const width of [1280, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    // No provider configuration is the reproduction's own state (the fixture
    // project attaches a runtime, so the panel is reached the same route every
    // other stream test uses; the invariant is checked over WHATEVER is
    // mounted, which already includes the composer's normal input row).
    await open(page, route(PART));
    await expect(page.locator('[data-testid="stream-panel"]')).toBeVisible();

    const escaped = await page.evaluate(() => {
      const asideEl = document.querySelector("aside");
      if (asideEl === null) throw new Error("no aside");
      const asideBox = asideEl.getBoundingClientRect();
      const bad: string[] = [];
      for (const node of asideEl.querySelectorAll("*")) {
        const box = node.getBoundingClientRect();
        if (box.width === 0 && box.height === 0) continue;
        if (box.right > asideBox.right + 1) {
          bad.push(
            `${node.tagName}.${String(node.className)} right ${String(Math.round(box.right))} > aside right ${String(Math.round(asideBox.right))}`,
          );
        }
      }
      return bad;
    });
    expect(escaped, `at ${String(width)}px`).toEqual([]);
  }
  await archive(page, testInfo, "stream-aside-descendant-invariant");
});

// --------------------------------------------------------------------------
// B-9 — the compact selected title is singular, but the session dropdown must
// retain every listed session after create and reload.

test("creating a session keeps every session in the dropdown, and the new one survives reload (B-9)", async ({
  page,
}, testInfo) => {
  await openSession(page, ORCHESTRATOR);
  await page.locator("[data-session-switch]").click();
  const before = await page
    .locator("[data-session-option]")
    .evaluateAll((nodes) =>
      nodes
        .map((node) => node.getAttribute("data-session-option"))
        .filter((id): id is string => id !== null),
    );
  expect(before.length).toBeGreaterThan(0);
  const beforeSet = new Set(before);
  await page.keyboard.press("Escape");

  const menuButton = page.locator("[data-session-create-menu]");
  if ((await menuButton.count()) > 0) await menuButton.click();
  await page.locator("[data-session-create]").first().click();
  const creation = page.getByRole("dialog", { name: "New conversation · Project", exact: true });
  await expect(creation).toContainText("Proposed default");
  await expect(creation.getByRole("button", { name: "Create conversation", exact: true })).toBeEnabled();
  await creation.getByRole("button", { name: "Create conversation", exact: true }).click();

  // Creation selects the new session in the compact header; it does not add a
  // second resting tab. Wait for that concrete result rather than a tab count.
  await expect
    .poll(async () => await page.locator("[data-session-tab]").getAttribute("data-session-tab"), {
      timeout: 30_000,
    })
    .not.toBe(ORCHESTRATOR);
  await expect(page.locator("[data-session-tab]")).toHaveCount(1);
  const created = await page.locator("[data-session-tab]").getAttribute("data-session-tab");
  expect(created, "the create action selected no new session").not.toBeNull();
  expect(beforeSet.has(created ?? ""), "the selected session was not new").toBe(false);

  const listing = await api<SessionsDocument>("/sessions");
  await page.locator("[data-session-switch]").click();
  const options = page.locator("[data-session-option]");
  await expect(options).toHaveCount(listing.sessions.length);
  const after = await options.evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-session-option")),
  );
  for (const id of before) {
    expect(after, `session ${id} disappeared from the dropdown after create`).toContain(id);
  }
  for (const row of listing.sessions) {
    expect(after, `listed session ${row.session_id} has no dropdown option`).toContain(
      row.session_id,
    );
  }
  expect(after).toContain(created);
  await page.keyboard.press("Escape");

  await page.reload();
  await expect(page.locator("[data-session-switch]")).toBeVisible();
  await page.locator("[data-session-switch]").click();
  await expect(page.locator(`[data-session-option="${created ?? ""}"]`)).toHaveCount(1);

  await archive(page, testInfo, "b9-create-keeps-strip");
});

// --------------------------------------------------------------------------
// J-web-stream-7 — one project observer owns transport for every conversation.
// Count every construction as well as the open set so a close/reopen duplicate
// cannot hide behind an unchanged steady-state count.

test("a load and session-dropdown switch keep one project WebSocket (J-web-stream-7)", async ({
  page,
}) => {
  await page.addInitScript(() => {
    const counters = { open: 0, total: 0 };
    (window as unknown as { __ws: typeof counters }).__ws = counters;
    const Native = window.WebSocket;
    class CountedSocket extends Native {
      constructor(...args: ConstructorParameters<typeof WebSocket>) {
        super(...args);
        counters.total += 1;
        counters.open += 1;
        this.addEventListener("close", () => {
          counters.open -= 1;
        });
      }
    }
    Object.defineProperty(window, "WebSocket", { value: CountedSocket, writable: true });
  });

  await openSession(page, ORCHESTRATOR);
  // Do not sample before connection. `data-stream=live` is written from the
  // socket status callback, so it is explicit evidence that construction and
  // subscription completed before the counters are inspected.
  await expect(page.locator('[data-testid="stream-panel"]')).toHaveAttribute(
    "data-stream",
    "live",
    { timeout: 60_000 },
  );
  await page.waitForTimeout(1_000);
  const afterLoad = await page.evaluate(
    () => (window as unknown as { __ws: { open: number; total: number } }).__ws,
  );
  expect(afterLoad.open, "project socket open after connection").toBe(1);
  expect(afterLoad.total, "duplicate socket constructed during load").toBe(1);

  // The observer already subscribes to the full listed set. Changing only the
  // selected conversation through the dropdown must not reconnect it.
  await page.locator("[data-session-switch]").click();
  await page.locator(`[data-session-option="${QUICK_EDIT}"]`).click();
  await expect(page.locator(`[data-session-tab="${QUICK_EDIT}"]`)).toHaveCount(1);
  await expect(page.locator('[data-testid="stream-panel"]')).toHaveAttribute("data-stream", "live");
  await page.waitForTimeout(1_000);
  const afterSwitch = await page.evaluate(
    () => (window as unknown as { __ws: { open: number; total: number } }).__ws,
  );
  expect(afterSwitch.open, "project socket open after the switch").toBe(1);
  expect(afterSwitch.total, "session selection constructed a duplicate socket").toBe(1);
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
    // §7.4(b), amended 2026-09-01: the socket's own answer is on the panel root
    // in every state, and that is what a gate reads. The badge is the DRAWN
    // exception — §7.4(a) forbids it for a `live` socket with no fault, so the
    // steady live state carries the attribute and mounts no element.
    await expect(page.locator('[data-testid="stream-panel"]')).toHaveAttribute(
      "data-stream",
      "live",
      { timeout: 60_000 },
    );
    await expect(page.locator("[data-stream-state]")).toHaveCount(0);

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

    // The successful outcome is concise at rest. Exact terminal provenance is
    // retained in the attribute/title and in a collapsed diagnostic; DOM
    // `textContent` includes that hidden JSON, so visible text is checked on
    // the resting outcome span rather than by pretending hidden text is drawn.
    const terminalId = await terminal.getAttribute("data-terminal-id");
    expect(terminalId, "the band minted no data-terminal-id to check against").toBeTruthy();
    const outcomeText = (await terminal.locator(":scope > span").first().innerText()) ?? "";
    expect(outcomeText).not.toBe("");
    expect(outcomeText).not.toContain(terminalId ?? "");
    await expect(terminal.locator(":scope > details")).not.toHaveAttribute("open", "");
    expect(await terminal.getAttribute("title")).toContain(terminalId ?? "");
    await expect(terminal.locator(":scope > details pre")).toContainText(terminalId ?? "");

    // §7.3 C1/C21 (amended 2026-09-02), the observer's negative halves: this
    // browser did not send the prompt, so it mints NO local-prompt echo — an
    // observer has no local text to echo — and, having attached with no
    // previous rendered live row and no echo to license one, it honestly
    // renders this first run with no top boundary. Boundaries begin at the
    // next run change, which this single-run test never reaches.
    await expect(page.locator('[data-row="local-prompt"]')).toHaveCount(0);
    await expect(page.locator('[data-row="run-start"]')).toHaveCount(0);

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
