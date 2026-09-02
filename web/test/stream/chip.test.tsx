// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The chip reads as a result, and §7.2's contract is untouched by it.
//
// This file is the pair to `toolSummary.test.ts`: that one asserts the decision,
// this one asserts the DOM the decision produces — and, more importantly, that
// making the chip readable did not weaken the attribute contract the gate reads.
// §7.2's predicate is a statement about `F`, the chip's `data-field` values, and
// `F` must still be exactly `keys(JSON.parse(payload.text))` even though every
// field row now lives inside a collapsed `<details>`. Both gates read the
// attribute set rather than visibility (`e2e/stream.spec.ts` through
// `evaluateAll`, `test/stream/components.test.tsx` through `querySelectorAll`),
// which is why the disclosure is sound and why this file says so out loud.
//
// The stylesheet assertions at the end are the layout half of the operator's
// block. jsdom cannot measure a pixel, so they are assertions about the CSS that
// ships — in `shell-layout.test.ts`'s idiom — and they exist because the failure
// was not a wrapping bug that a longer column would have hidden: the track had
// resolved to zero width, and `.code`'s `word-break: break-all` then rendered a
// sha256 one character per line.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { ToolChip } from "../../src/components/stream/ToolChip";
import { Transcript } from "../../src/components/stream/Transcript";
import { copy } from "../../src/copy";
import { groupRows, liveItem } from "../../src/stream/transcript";
import type { PanelRow, TranscriptItem } from "../../src/stream/transcript";

const RUN = "run-aabbccddeeff";
const SESSION = "sess-kerf";

/** The digest the operator's own transcript rendered as a vertical letter stack. */
const STATE_HASH =
  "sha256:ad206068c29722297302d4fadb11c198d45356f4a95c31f0b8f9d4d6f1a2b3c4d";

const RESULT_DOC = {
  status: "ok",
  part: "kerf_card",
  part_param_state_hash: STATE_HASH,
  source_ref: "artifact:source:sha256:1122334455667788990011223344556677889900aabbccdd",
};

function call(seq: number): TranscriptItem {
  return liveItem({
    run_id: RUN,
    seq,
    kind: "tool_call",
    session_id: SESSION,
    tool_call_id: "call-read-1",
    payload: { name: "read_part", arguments: { name: "kerf_card", limit_lines: 2000 } },
  });
}

function result(seq: number): TranscriptItem {
  return liveItem({
    run_id: RUN,
    seq,
    kind: "tool_result",
    session_id: SESSION,
    tool_call_id: "call-read-1",
    payload: { toolName: "read_part", isError: false, text: JSON.stringify(RESULT_DOC) },
  });
}

function chipDocument(): Element {
  const markup = renderToStaticMarkup(
    <ToolChip toolName="read_part" call={call(1)} result={result(2)} images={[]} status="ok" />,
  );
  const parsed = new DOMParser().parseFromString(`<body>${markup}</body>`, "text/html");
  const chip = parsed.querySelector("[data-tool-name]");
  if (chip === null) throw new Error("the chip did not render");
  return chip;
}

describe("a successful call reads as an outcome (§7.2, §3.3)", () => {
  const chip = chipDocument();

  it("leads with the tool name, the status word, and a headline", () => {
    expect(chip.getAttribute("data-tool-name")).toBe("read_part");
    expect(chip.getAttribute("data-status")).toBe("ok");
    expect(chip.querySelector("[data-chip-status]")?.getAttribute("data-chip-status")).toBe("ok");
    const summary = chip.querySelector("[data-chip-summary]");
    expect(summary?.getAttribute("data-chip-summary")).toBe("fields");
    expect(summary?.textContent ?? "").toContain("kerf_card");
  });

  it("puts no digest in the chip's own visible text", () => {
    // The headline plus the disclosure's own label — everything above the
    // `<details>`. This is the assertion that fails if a hash is ever promoted
    // back onto the reading surface.
    const summary = chip.querySelector("[data-chip-summary]");
    expect(summary?.textContent ?? "").not.toContain("ad206068");
    expect(summary?.textContent ?? "").not.toContain("sha256:");
  });

  it("shows a shortened digest in the field row, with the whole value beside it", () => {
    const field = chip.querySelector('[data-field="part_param_state_hash"]');
    const value = field?.querySelector("dd");
    expect(value?.textContent ?? "").not.toBe(STATE_HASH);
    expect((value?.textContent ?? "").length).toBeLessThan(STATE_HASH.length);
    // `title` carries the identity, so an elision never destroys one.
    expect(value?.getAttribute("title")).toBe(STATE_HASH);
  });

  it("puts the call operand on a running chip, without inventing a data-field", () => {
    const markup = renderToStaticMarkup(
      <ToolChip toolName="read_part" call={call(1)} result={null} images={[]} status="running" />,
    );
    const parsed = new DOMParser().parseFromString(`<body>${markup}</body>`, "text/html");
    const chip = parsed.querySelector("[data-tool-name]");
    expect(chip?.getAttribute("data-status")).toBe("running");
    expect(chip?.querySelector("[data-chip-summary]")?.textContent ?? "").toContain("kerf_card");
    expect(chip?.querySelectorAll("[data-field]")).toHaveLength(0);
  });

  it("carries the whole result document behind ONE collapsed disclosure", () => {
    const detail = chip.querySelector("[data-chip-detail]");
    expect(detail?.tagName.toLowerCase()).toBe("details");
    // Collapsed: a chip that opened itself would be the wall again.
    expect(detail?.hasAttribute("open")).toBe(false);
    expect(chip.querySelectorAll("[data-chip-detail]")).toHaveLength(1);
    // The arguments moved in with it. They carry no `data-field` — that
    // attribute names keys of the RESULT document, and an argument under it
    // would break groundedness on the very attribute the gate reads.
    expect(detail?.textContent ?? "").toContain("limit_lines");
    expect(detail?.querySelectorAll("[data-field]").length).toBe(
      Object.keys(RESULT_DOC).length,
    );
  });
});

describe("§7.2's field contract survives the disclosure", () => {
  const chip = chipDocument();

  it("renders `F = keys(D)`, in the document's own order", () => {
    const fields = [...chip.querySelectorAll("[data-field]")].map(
      (node) => node.getAttribute("data-field") ?? "",
    );
    expect(fields).toEqual(Object.keys(RESULT_DOC));
  });

  it("still marks §7.2's references", () => {
    const refs = [...chip.querySelectorAll('[data-field-reference="true"]')].map(
      (node) => node.getAttribute("data-field") ?? "",
    );
    expect(refs).toEqual(["source_ref"]);
  });

  it("keeps the parsed field state and the result's own identity", () => {
    expect(chip.getAttribute("data-field-state")).toBe("parsed");
    const fields = chip.querySelector("dl");
    expect(fields?.getAttribute("data-event-id")).toBe(`${RUN}#2`);
    expect(fields?.getAttribute("data-surface")).toBe("live");
  });

  it("names the absence rather than a headline when a result is only identifiers", () => {
    const opaque = liveItem({
      run_id: RUN,
      seq: 4,
      kind: "tool_result",
      session_id: SESSION,
      tool_call_id: "call-read-1",
      payload: {
        toolName: "build_part",
        isError: false,
        // A non-ref hash key: C23's tier (4) licenses only `*_ref` keys onto
        // the line abbreviated, so this document still has nothing legible and
        // the opaque fallback renders unchanged.
        text: JSON.stringify({
          build_state_hash:
            "sha256:83f4822a7943a7baf11b29d15c8af23c341fb4c0bfff352ac44a3f67d4bac82b",
        }),
      },
    });
    const buildCall = liveItem({
      run_id: RUN,
      seq: 3,
      kind: "tool_call",
      session_id: SESSION,
      tool_call_id: "call-read-1",
      payload: { name: "build_part", arguments: {} },
    });
    const markup = renderToStaticMarkup(
      <ToolChip toolName="build_part" call={buildCall} result={opaque} images={[]} status="ok" />,
    );
    const parsed = new DOMParser().parseFromString(`<body>${markup}</body>`, "text/html");
    expect(parsed.querySelector("[data-chip-summary]")?.getAttribute("data-chip-summary")).toBe(
      "opaque",
    );
    // The hash is still a `data-field` node, so containment holds.
    expect(parsed.querySelectorAll('[data-field="build_state_hash"]')).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// §7.2 (a)-(d), amended 2026-09-01: the resting face, and repetition
// ---------------------------------------------------------------------------

const REPEAT_RUN = "run-repeat000000";
const REPEAT_DOC = { status: "ok", check_set_generation: "0", total: 1 };

/** `n` identical successful `list_project_checks` calls, back to back. */
function repeatItems(n: number, args: (index: number) => unknown = () => ({})): TranscriptItem[] {
  const items: TranscriptItem[] = [];
  for (let index = 0; index < n; index += 1) {
    items.push(
      liveItem({
        run_id: REPEAT_RUN,
        seq: index * 2,
        kind: "tool_call",
        session_id: SESSION,
        tool_call_id: `c-scan-${String(index)}`,
        payload: { name: "list_project_checks", arguments: args(index) },
      }),
      liveItem({
        run_id: REPEAT_RUN,
        seq: index * 2 + 1,
        kind: "tool_result",
        session_id: SESSION,
        tool_call_id: `c-scan-${String(index)}`,
        payload: {
          toolName: "list_project_checks",
          isError: false,
          text: JSON.stringify(REPEAT_DOC),
        },
      }),
    );
  }
  return items;
}

function renderRows(rows: readonly PanelRow[]): Document {
  const markup = renderToStaticMarkup(<Transcript rows={rows} />);
  return new DOMParser().parseFromString(`<body>${markup}</body>`, "text/html");
}

describe("a repeat group renders as one row, and drops no id (§7.2 (a))", () => {
  const items = repeatItems(3);
  const document_ = renderRows(groupRows(items));
  const chips = [...document_.querySelectorAll("[data-tool-name]")];

  it("renders one chip for three calls, with the count and the shared badge", () => {
    expect(chips).toHaveLength(1);
    const chip = chips[0];
    expect(chip?.getAttribute("data-chip-repeat")).toBe("3");
    expect(chip?.getAttribute("data-status")).toBe("ok");
    expect(chip?.querySelector("header")?.textContent ?? "").toContain("×3");
  });

  it("keeps the set of rendered ids equal to the tool-call event ids", () => {
    // §7.2 (a)'s own test, as amended 2026-09-01. `data-event-id` ∪
    // `data-event-ids`, per node, across every element of the transcript — a
    // coalescing that loses an id fails. SET, not multiset, and the clause now
    // says so: the anchor id is published twice on purpose (as `data-event-id`
    // so addressing resolves, and again as the first entry of `data-event-ids`
    // so the member list is complete), which a multiset comparison would count
    // twice and fail on a correct render.
    const rendered = new Set<string>();
    for (const node of document_.querySelectorAll("[data-event-id], [data-event-ids]")) {
      const single = node.getAttribute("data-event-id");
      if (single !== null) rendered.add(single);
      for (const id of (node.getAttribute("data-event-ids") ?? "").split(" ")) {
        if (id !== "") rendered.add(id);
      }
    }
    expect([...rendered].sort()).toEqual(items.map((item) => item.eventId).sort());
  });

  it("anchors on the first member and pluralizes the tool-call id", () => {
    const chip = chips[0];
    expect(chip?.getAttribute("data-event-id")).toBe(`${REPEAT_RUN}#0`);
    expect(chip?.getAttribute("data-event-ids")).toBe(
      `${REPEAT_RUN}#0 ${REPEAT_RUN}#2 ${REPEAT_RUN}#4`,
    );
    expect(chip?.getAttribute("data-tool-call-ids")).toBe("c-scan-0 c-scan-1 c-scan-2");
    // "`data-tool-call-id` … becomes `data-tool-call-ids` on a coalesced row".
    expect(chip?.hasAttribute("data-tool-call-id")).toBe(false);
  });

  it("renders the shared document's fields once, and still headlines it", () => {
    const chip = chips[0];
    const fields = [...(chip?.querySelectorAll("[data-field]") ?? [])].map(
      (node) => node.getAttribute("data-field") ?? "",
    );
    expect(fields).toEqual(Object.keys(REPEAT_DOC));
    // §7.2 (d): a coalesced row is never `data-chip-summary` absent.
    expect(chip?.querySelector("[data-chip-summary]")).not.toBeNull();
  });

  it("names every distinct argument document the members actually sent", () => {
    const mixed = renderRows(
      groupRows(repeatItems(3, (index) => (index === 2 ? { deep: true } : {}))),
    );
    const detail = mixed.querySelector("[data-chip-detail]");
    expect(mixed.querySelectorAll("[data-tool-name]")).toHaveLength(1);
    expect(detail?.textContent ?? "").toContain("deep");
    // Two distinct argument documents, the first sent by two of the three.
    expect(detail?.querySelectorAll("[class*='args']").length).toBeGreaterThan(1);
  });

  it("does not coalesce when the calls are not identical (the negative half)", () => {
    const differing = repeatItems(2);
    const second = differing[3];
    expect(second).toBeDefined();
    const items_ = [
      ...differing.slice(0, 3),
      liveItem({
        run_id: REPEAT_RUN,
        seq: 3,
        kind: "tool_result",
        session_id: SESSION,
        tool_call_id: "c-scan-1",
        payload: {
          toolName: "list_project_checks",
          isError: false,
          text: JSON.stringify({ ...REPEAT_DOC, total: 2 }),
        },
      }),
    ];
    const document2 = renderRows(groupRows(items_));
    const rendered = [...document2.querySelectorAll("[data-tool-name]")];
    expect(rendered).toHaveLength(2);
    for (const chip of rendered) {
      expect(chip.hasAttribute("data-chip-repeat")).toBe(false);
      expect(chip.getAttribute("data-tool-call-id")).toBeTruthy();
    }
  });
});

// ---------------------------------------------------------------------------
// §7.2 C4/C5, amended 2026-09-02: cycle groups
// ---------------------------------------------------------------------------

const CYCLE_RUN = "run-cycle0000000";
const CYCLE_DOC = { status: "ok", total: 1 };

/** `n` (identical ok call+result, narration) triples, back to back. */
function cycleItems(n: number, fail: (index: number) => boolean = () => false): TranscriptItem[] {
  const items: TranscriptItem[] = [];
  for (let index = 0; index < n; index += 1) {
    items.push(
      liveItem({
        run_id: CYCLE_RUN,
        seq: index * 3,
        kind: "tool_call",
        session_id: SESSION,
        tool_call_id: `cy-${String(index)}`,
        payload: { name: "list_project_checks", arguments: { probe: index } },
      }),
      liveItem({
        run_id: CYCLE_RUN,
        seq: index * 3 + 1,
        kind: "tool_result",
        session_id: SESSION,
        tool_call_id: `cy-${String(index)}`,
        payload: {
          toolName: "list_project_checks",
          isError: fail(index),
          text: JSON.stringify(CYCLE_DOC),
        },
      }),
      liveItem({
        run_id: CYCLE_RUN,
        seq: index * 3 + 2,
        kind: "text_delta",
        session_id: SESSION,
        payload: { text: `Narration ${String(index)}.` },
      }),
    );
  }
  return items;
}

describe("a cycle group renders first pair full, then compact lines (§7.2 C4)", () => {
  const items = cycleItems(3);
  const document_ = renderRows(groupRows(items));

  it("renders one full chip, the first pair's text row, and one compact line per subsequent pair", () => {
    const row = document_.querySelector('[data-row="cycle"]');
    expect(row).not.toBeNull();
    expect(row?.getAttribute("data-cycle")).toBe("3");
    // Exactly one full chip — the first pair's — and two compact lines.
    expect(row?.querySelectorAll("[data-tool-name]")).toHaveLength(1);
    const lines = [...(row?.querySelectorAll("[data-cycle-line]") ?? [])];
    expect(lines.map((line) => line.getAttribute("data-cycle-line"))).toEqual(["2", "3"]);
    // The running ×N ordinal, the tool name, the shared status badge — and
    // nothing else: no summary, no fields, no disclosure of its own.
    for (const [index, line] of lines.entries()) {
      expect(line.textContent ?? "").toContain("list_project_checks");
      expect(line.textContent ?? "").toContain(`×${String(index + 2)}`);
      expect(line.querySelector("[data-chip-status]")?.getAttribute("data-chip-status")).toBe("ok");
      expect(line.querySelector("[data-chip-summary]")).toBeNull();
      expect(line.querySelector("[data-field]")).toBeNull();
      expect(line.querySelector("[data-chip-detail]")).toBeNull();
    }
  });

  it("folds the subsequent text rows and Detail behind the FIRST pair's one disclosure", () => {
    const row = document_.querySelector('[data-row="cycle"]');
    // One disclosure opens the whole cycle.
    expect(row?.querySelectorAll("[data-chip-detail]")).toHaveLength(1);
    const detail = row?.querySelector("[data-chip-detail]");
    const folds = [...(detail?.querySelectorAll("[data-cycle-fold]") ?? [])];
    expect(folds.map((fold) => fold.getAttribute("data-cycle-fold"))).toEqual(["2", "3"]);
    // Text content is RELOCATED, never elided (C5): the folded narration is in
    // the DOM, with its own event id span.
    expect(folds[0]?.textContent ?? "").toContain("Narration 1.");
    expect(folds[1]?.textContent ?? "").toContain("Narration 2.");
    expect(folds[0]?.querySelector(`[data-event-id="${CYCLE_RUN}#5"]`)).not.toBeNull();
    // The first pair's own narration renders in place, outside the disclosure.
    const fullText = [...(row?.querySelectorAll("p") ?? [])].find((node) =>
      (node.textContent ?? "").includes("Narration 0."),
    );
    expect(fullText).toBeDefined();
    expect(fullText?.closest("[data-chip-detail]")).toBeNull();
  });

  it("keeps the transcript-wide id set equal to the events' — C5's testable", () => {
    const rendered = new Set<string>();
    for (const node of document_.querySelectorAll("[data-event-id], [data-event-ids]")) {
      const single = node.getAttribute("data-event-id");
      if (single !== null) rendered.add(single);
      for (const id of (node.getAttribute("data-event-ids") ?? "").split(" ")) {
        if (id !== "") rendered.add(id);
      }
    }
    expect([...rendered].sort()).toEqual(items.map((item) => item.eventId).sort());
  });

  it("carries each folded pair's event ids and tool-call ids on its compact line", () => {
    const lines = [...document_.querySelectorAll("[data-cycle-line]")];
    expect(lines[0]?.getAttribute("data-event-ids")).toBe(`${CYCLE_RUN}#3 ${CYCLE_RUN}#4`);
    expect(lines[0]?.getAttribute("data-tool-call-ids")).toBe("cy-1");
    expect(lines[1]?.getAttribute("data-event-ids")).toBe(`${CYCLE_RUN}#6 ${CYCLE_RUN}#7`);
    expect(lines[1]?.getAttribute("data-tool-call-ids")).toBe("cy-2");
    // The first pair's chip still anchors `data-event-id`, unchanged.
    expect(
      document_.querySelector('[data-row="cycle"] [data-tool-name]')?.getAttribute("data-event-id"),
    ).toBe(`${CYCLE_RUN}#0`);
  });

  it("renders each folded pair's distinct argument document in its fold — the chips' Detail", () => {
    const detail = document_.querySelector('[data-row="cycle"] [data-chip-detail]');
    // Each member sent a distinct `probe`, and each fold names its own.
    expect(detail?.querySelector('[data-cycle-fold="2"]')?.textContent ?? "").toContain('"probe":1');
    expect(detail?.querySelector('[data-cycle-fold="3"]')?.textContent ?? "").toContain('"probe":2');
  });

  it("does NOT fold when a member failed — the negative half in the DOM", () => {
    const failed = renderRows(groupRows(cycleItems(3, (index) => index === 2)));
    expect(failed.querySelector('[data-row="cycle"]')).toBeNull();
    expect(failed.querySelectorAll("[data-cycle-line]")).toHaveLength(0);
    expect(failed.querySelectorAll("[data-tool-name]")).toHaveLength(3);
  });
});

describe("the field count is inside the disclosure, never on the face (§7.2 (b))", () => {
  const hosts: HTMLElement[] = [];

  afterEach(() => {
    for (const host of hosts.splice(0)) host.remove();
  });

  function mount(rows: readonly PanelRow[]): HTMLElement {
    const host = document.createElement("div");
    document.body.append(host);
    hosts.push(host);
    const root = createRoot(host);
    act(() => {
      root.render(<Transcript rows={rows} />);
    });
    return host;
  }

  function occurrences(text: string, needle: string): number {
    return text.split(needle).length - 1;
  }

  it("renders the string on no chip while every disclosure is closed", () => {
    const host = mount(groupRows([...repeatItems(2), ...call2()]));
    const details = [...host.querySelectorAll("details[data-chip-detail]")];
    expect(details.length).toBeGreaterThan(1);
    for (const node of details) expect(node.hasAttribute("open")).toBe(false);
    expect(occurrences(host.textContent ?? "", "result field")).toBe(0);
    // The `data-field` nodes are unchanged in both states — the count was
    // chrome about a list, not the list.
    expect(host.querySelectorAll("[data-field]").length).toBeGreaterThan(0);
  });

  it("renders it exactly once when one disclosure is opened", () => {
    const host = mount(groupRows([...repeatItems(2), ...call2()]));
    const fieldsBefore = host.querySelectorAll("[data-field]").length;
    const first = host.querySelector("details[data-chip-detail]");
    expect(first).not.toBeNull();
    act(() => {
      if (first instanceof HTMLDetailsElement) {
        first.open = true;
        first.dispatchEvent(new Event("toggle"));
      }
    });
    expect(occurrences(host.textContent ?? "", copy.stream.chip.detail(3))).toBe(1);
    expect(host.querySelectorAll("[data-chip-detail-count]")).toHaveLength(1);
    expect(host.querySelectorAll("[data-field]").length).toBe(fieldsBefore);
  });
});

/** A second, different chip, so "no chip renders it" has more than one chip. */
function call2(): TranscriptItem[] {
  return [
    liveItem({
      run_id: REPEAT_RUN,
      seq: 900,
      kind: "tool_call",
      session_id: SESSION,
      tool_call_id: "c-other",
      payload: { name: "read_part", arguments: { name: "kerf_card" } },
    }),
    liveItem({
      run_id: REPEAT_RUN,
      seq: 901,
      kind: "tool_result",
      session_id: SESSION,
      tool_call_id: "c-other",
      payload: {
        toolName: "read_part",
        isError: false,
        text: JSON.stringify({ status: "ok", part: "kerf_card", line_count: 12 }),
      },
    }),
  ];
}

describe("at most one preamble note, and never above the headline (§7.2 (c))", () => {
  function orphan(isError: boolean | null): TranscriptItem {
    return liveItem({
      run_id: REPEAT_RUN,
      seq: 11,
      kind: "tool_result",
      session_id: SESSION,
      tool_call_id: "c-orphan",
      payload: { toolName: "read_part", isError, text: "{}" },
    });
  }

  function chipOf(markup: string): Element {
    const parsed = new DOMParser().parseFromString(`<body>${markup}</body>`, "text/html");
    const chip = parsed.querySelector("[data-tool-name]");
    if (chip === null) throw new Error("the chip did not render");
    return chip;
  }

  it("renders no note at all for a successful call with a result", () => {
    const chip = chipDocument();
    expect(chip.textContent ?? "").not.toContain(copy.stream.chip.runningWhy);
    expect(chip.textContent ?? "").not.toContain(copy.stream.chip.unknownWhy);
    expect(chip.textContent ?? "").not.toContain(copy.stream.chip.callMissing);
    expect(chip.hasAttribute("title")).toBe(false);
  });

  it("renders exactly one note for a running call, below the headline", () => {
    const chip = chipOf(
      renderToStaticMarkup(
        <ToolChip toolName="read_part" call={call(1)} result={null} images={[]} status="running" />,
      ),
    );
    expect(chip.textContent ?? "").toContain(copy.stream.chip.runningWhy);
    const nodes = [...chip.children];
    const summaryAt = nodes.findIndex((node) => node.hasAttribute("data-chip-summary"));
    const noteAt = nodes.findIndex((node) =>
      (node.textContent ?? "").includes(copy.stream.chip.runningWhy),
    );
    expect(summaryAt).toBeGreaterThanOrEqual(0);
    expect(noteAt).toBeGreaterThan(summaryAt);
  });

  it("draws the most specific note and keeps the suppressed one on `title`", () => {
    // An orphan result whose failure flag is unrecoverable is BOTH
    // `callMissing` and `unknown`. §7.2 (c)'s precedence draws the first;
    // the second is not lost, it moves to the chip's `title`.
    const item = orphan(null);
    const chip = chipOf(
      renderToStaticMarkup(
        <ToolChip toolName="read_part" call={item} result={item} images={[]} status="unknown" />,
      ),
    );
    const notes = [...chip.children].filter((node) =>
      [copy.stream.chip.callMissing, copy.stream.chip.unknownWhy, copy.stream.chip.runningWhy].some(
        (text) => (node.textContent ?? "") === text,
      ),
    );
    expect(notes).toHaveLength(1);
    expect(notes[0]?.textContent).toBe(copy.stream.chip.callMissing);
    expect(chip.getAttribute("title") ?? "").toContain(copy.stream.chip.unknownWhy);
  });
});

describe("the field grid cannot collapse a track to zero again", () => {
  const css = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "../../src/components/stream/Transcript.module.css"),
    "utf8",
  ).replace(/\/\*[\s\S]*?\*\//g, "");

  it("stacks the fields instead of dealing them across shared columns", () => {
    // The bug: `.fields` was a three-column grid and each `.field` was a single
    // grid ITEM, so auto-placement put field 1 in column 1, field 2 in column 2
    // and field 3 in column 3.
    expect(css).toMatch(/\.fields\s*\{[^}]*display:\s*flex/);
    expect(css).toMatch(/\.fields\s*\{[^}]*flex-direction:\s*column/);
    expect(css).toMatch(/\.field\s*\{[^}]*display:\s*grid/);
  });

  it("bounds every track a field's own content can size", () => {
    // `max-content` is what let one digest take the whole width and leave the
    // `minmax(0, …)` tracks at zero. No unbounded track may reach these rows,
    // and no track may be shared between two fields.
    const rows = /\.field\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(rows).toContain("minmax(0,");
    expect(rows).not.toContain("max-content");
    const fields = /\.fields\s*\{([^}]*)\}/.exec(css)?.[1] ?? "";
    expect(fields).not.toContain("max-content");
    expect(fields).not.toContain("grid-template-columns");
  });

  it("gives the collapsed disclosures a visible marker", () => {
    // `display: flex` on a `<summary>` drops the browser's own triangle, which
    // is how the shipped `.rawSummary` became a control with nothing saying it
    // opened.
    expect(css).toMatch(/\.detailSummary::before[\s\S]*?content:/);
    expect(css).toMatch(/details\[open\][\s\S]*?\.detailSummary::before[\s\S]*?content:/);
  });

  it("lets both cells shrink below their own min-content", () => {
    expect(css).toMatch(/\.field\s*\{[^}]*min-width:\s*0/);
    expect(css).toMatch(/\.fieldValue\s*\{[^}]*min-width:\s*0/);
    expect(css).toMatch(/\.fieldValue\s*\{[^}]*overflow-wrap:\s*anywhere/);
  });

  it("caps a cycle's compact line at 1.5× target-min — 36px (§7.2 C4)", () => {
    // jsdom cannot measure the box, so the ceiling is asserted on the CSS
    // that ships, in this file's own idiom.
    expect(css).toMatch(/\.cycleLine\s*\{[^}]*max-block-size:\s*36px/);
  });
});
