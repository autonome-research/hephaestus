// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { Transcript } from "../../src/components/stream/Transcript";
import { copy } from "../../src/copy";
import { groupRows, liveItem, type TranscriptItem } from "../../src/stream/transcript";

const HASH = `sha256:${"abc123".repeat(12)}`;
const DOC = { status: "ok", total: 1, state_hash: HASH, source_ref: "artifact:source:123" };
function call(n: number): TranscriptItem {
  return liveItem({ run_id: "run-tools", session_id: "session-tools", seq: n * 3,
    kind: "tool_call", tool_call_id: `call-${n}`,
    payload: { name: "read_part", arguments: { probe: n } } });
}
function result(n: number, text = JSON.stringify(DOC), isError: boolean | null = false): TranscriptItem {
  return liveItem({ run_id: "run-tools", session_id: "session-tools", seq: n * 3 + 1,
    kind: "tool_result", tool_call_id: `call-${n}`,
    payload: { toolName: "read_part", text, isError } });
}
function narration(n: number): TranscriptItem {
  return liveItem({ run_id: "run-tools", session_id: "session-tools", seq: n * 3 + 2,
    kind: "text_delta", payload: { text: "Same actual narration." } });
}
function render(items: readonly TranscriptItem[]): Document {
  return new DOMParser().parseFromString(renderToStaticMarkup(<Transcript rows={groupRows(items)} />), "text/html");
}
function ids(host: ParentNode): string[] {
  return [...host.querySelectorAll("[data-event-id]")].map((node) => node.getAttribute("data-event-id") ?? "");
}

describe("individual compact tool disclosures", () => {
  it("lists EACH repeated call, collapsed, with its own args and exact full result", () => {
    const items = [0, 1, 2].flatMap((n) => [call(n), result(n)]);
    const doc = render(items);
    const chips = [...doc.querySelectorAll("[data-tool-name]")];
    expect(chips).toHaveLength(3);
    expect(doc.querySelector("[data-chip-repeat]")).toBeNull();
    for (const [n, chip] of chips.entries()) {
      expect(chip.getAttribute("data-tool-call-id")).toBe(`call-${n}`);
      expect(chip.getAttribute("data-status")).toBe("ok");
      const detail = chip.querySelector("details");
      expect(detail?.hasAttribute("open")).toBe(false);
      expect(chip.querySelectorAll("details")).toHaveLength(1);
      expect(detail?.querySelector("summary")?.textContent).toContain("read_part");
      expect(detail?.querySelector("summary")?.textContent).toContain(copy.stream.chip.status.ok);
      expect(detail?.querySelector("summary")?.textContent).not.toContain(HASH);
      expect(detail?.querySelector("summary")?.textContent).not.toContain("probe");
      expect(detail?.textContent).toContain(`"probe":${n}`);
      expect([...chip.querySelectorAll("[data-field]")].map((field) => field.getAttribute("data-field")))
        .toEqual(Object.keys(DOC));
      expect(chip.querySelector('[data-field="state_hash"] dd')?.textContent).toBe(HASH);
      expect(chip.querySelector('[data-field="source_ref"]')?.getAttribute("data-field-reference")).toBe("true");
    }
    // Multiset equality: every identity exactly once, not just present in a set.
    expect(ids(doc)).toEqual(items.map((item) => item.eventId));
  });

  it("keeps every repeated narration outside disclosures, in call/result order", () => {
    const items = [0, 1, 2].flatMap((n) => [call(n), result(n), narration(n)]);
    const doc = render(items);
    expect(doc.querySelectorAll("[data-tool-name]")).toHaveLength(3);
    expect(doc.querySelector("[data-row='cycle']")).toBeNull();
    expect([...doc.querySelectorAll("[data-row]")].map((node) => node.getAttribute("data-row")))
      .toEqual(["chip", "text", "chip", "text", "chip", "text"]);
    const prose = [...doc.querySelectorAll("[data-row='text']")];
    expect(prose).toHaveLength(3);
    for (const node of prose) {
      expect(node.textContent).toBe("Same actual narration.");
      expect(node.closest("details")).toBeNull();
    }
    expect(ids(doc)).toEqual(items.map((item) => item.eventId));
  });

  it("keeps failed calls prominent and separately inspectable, including raw failures", () => {
    const doc = render([call(0), result(0, "Actual provider/tool failure", true),
      call(1), result(1, "Actual provider/tool failure", true)]);
    expect(doc.querySelectorAll('[data-status="error"]')).toHaveLength(2);
    for (const chip of doc.querySelectorAll('[data-status="error"]')) {
      expect(chip.querySelector("summary")?.textContent).toContain("Failed");
      expect(chip.querySelector("article > p")?.textContent).toBe(copy.stream.chip.failed);
      expect(chip.querySelector("pre")?.textContent).toBe("Actual provider/tool failure");
      expect(chip.querySelectorAll("[data-field]")).toHaveLength(0);
    }
  });

  it("does not claim missing or unknown tool outcomes are running or successful", () => {
    const doc = render([call(0), call(1), result(1, "distance: 12.5 mm", null)]);
    const summaries = [...doc.querySelectorAll("summary")].map((node) => node.textContent);
    expect(summaries).toEqual(["read_partNo result", "read_partUnknown"]);
    expect(doc.body.textContent).toContain(copy.stream.chip.runningWhy);
    expect(doc.body.textContent).toContain(copy.stream.chip.unknownWhy);
    expect(doc.body.textContent).toContain("distance: 12.5 mm");
  });

  it("preserves orphan and malformed result identities without inventing fields", () => {
    const orphan = result(3, "not json", null);
    const malformed = { ...result(4), payload: null };
    const doc = render([orphan, call(4), malformed]);
    expect(ids(doc)).toEqual([orphan.eventId, call(4).eventId, malformed.eventId]);
    expect(doc.body.textContent).toContain(copy.stream.chip.callMissing);
    expect(doc.querySelectorAll("[data-field]")).toHaveLength(0);
  });
});

describe("streaming disclosure identity and native accessibility", () => {
  let root: Root | null = null;
  let host: HTMLDivElement;
  afterEach(() => { act(() => root?.unmount()); host.remove(); });

  function mount(items: readonly TranscriptItem[]): void {
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    update(items);
  }
  function update(items: readonly TranscriptItem[]): void {
    act(() => root?.render(<Transcript rows={groupRows(items)} />));
  }
  function toggle(detail: HTMLDetailsElement, open: boolean): void {
    act(() => { detail.open = open; detail.dispatchEvent(new Event("toggle")); });
  }

  it("retains focus and independent expansion when results create and break repeat groups", () => {
    mount([call(0), call(1)]);
    const details = [...host.querySelectorAll<HTMLDetailsElement>("details")];
    const first = details[0]!;
    const second = details[1]!;
    const summary = second.querySelector("summary")!;
    summary.focus();
    toggle(second, true);
    update([call(0), result(0), call(1), result(1)]);
    expect(host.querySelectorAll("details")[1]).toBe(second);
    expect(document.activeElement).toBe(summary);
    expect(second.open).toBe(true);
    expect(first.open).toBe(false);
    expect(summary.getAttribute("aria-expanded")).toBe("true");
    expect(second.querySelectorAll("[data-field]")).toHaveLength(Object.keys(DOC).length);
    update([call(0), result(0), call(1), result(1, "failed", true)]);
    expect(host.querySelectorAll("details")[1]).toBe(second);
    expect(second.open).toBe(true);
    toggle(second, false);
    expect(summary.getAttribute("aria-expanded")).toBe("false");
  });

  it("retains expansion as the third narration creates a cycle group", () => {
    const firstTwo = [0, 1].flatMap((n) => [call(n), result(n), narration(n)]);
    mount(firstTwo);
    const second = host.querySelectorAll<HTMLDetailsElement>("details")[1]!;
    toggle(second, true);
    update([...firstTwo, call(2), result(2), narration(2)]);
    expect(host.querySelectorAll("details")[1]).toBe(second);
    expect(second.open).toBe(true);
    expect(host.querySelectorAll("[data-row='text']")).toHaveLength(3);
  });

  it("keeps reasoning open as additional deltas arrive, without token-count chrome", () => {
    const thought = { ...narration(0), kind: "thought", rawKind: "thought" } as const;
    mount([thought]);
    const detail = host.querySelector<HTMLDetailsElement>("details")!;
    toggle(detail, true);
    update([thought, { ...thought, eventId: "run-tools#99", seq: 99 }]);
    expect(host.querySelector("details")).toBe(detail);
    expect(detail.open).toBe(true);
    expect(detail.querySelector("summary")?.textContent).toBe(copy.stream.thought);
    expect(ids(host)).toEqual([thought.eventId, "run-tools#99"]);
  });
});

describe("compact tool layout and bounded fields", () => {
  const css = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../../src/components/stream/Transcript.module.css"), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "");
  it("uses a single compact disclosure face, not a padded raised card", () => {
    expect(css).toMatch(/\.chip\s*\{[^}]*padding:\s*0/);
    expect(css).toMatch(/\.chip\s*\{[^}]*background:\s*transparent/);
    expect(css).toMatch(/\.toolSummary\s*\{[^}]*min-height:\s*var\(--target-min\)/);
    expect(css).toMatch(/\.toolSummary::before\s*\{[^}]*content:/);
    expect(css).toMatch(/summary:focus-visible\s*\{[^}]*outline:/);
  });
  it("stacks fields and lets long values wrap without zero-width shared tracks", () => {
    expect(css).toMatch(/\.fields\s*\{[^}]*flex-direction:\s*column/);
    expect(css).toMatch(/\.field\s*\{[^}]*minmax\(0, 1fr\)/);
    expect(css).toMatch(/\.fieldValue\s*\{[^}]*min-width:\s*0/);
    expect(css).toMatch(/\.fieldValue\s*\{[^}]*overflow-wrap:\s*anywhere/);
  });
});
