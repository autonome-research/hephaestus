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
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ToolChip } from "../../src/components/stream/ToolChip";
import { liveItem } from "../../src/stream/transcript";
import type { TranscriptItem } from "../../src/stream/transcript";

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
        text: JSON.stringify({
          artifact_ref:
            "artifact:build:sha256:83f4822a7943a7baf11b29d15c8af23c341fb4c0bfff352ac44a3f67d4bac82b",
        }),
      },
    });
    const markup = renderToStaticMarkup(
      <ToolChip toolName="build_part" call={call(3)} result={opaque} images={[]} status="ok" />,
    );
    const parsed = new DOMParser().parseFromString(`<body>${markup}</body>`, "text/html");
    expect(parsed.querySelector("[data-chip-summary]")?.getAttribute("data-chip-summary")).toBe(
      "opaque",
    );
    // The ref is still a `data-field` node, so containment holds.
    expect(parsed.querySelectorAll('[data-field="artifact_ref"]')).toHaveLength(1);
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
});
