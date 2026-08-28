// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §7.2's field predicate, asserted mechanically against the generated tool
// schemas and the recorded normalized events.
//
// The predicate, restated: with `D = JSON.parse(payload.text)`, `K = keys(D)`,
// `R` = the tool's required output fields from `schemas/tools/<name>.schema.json`,
// `references(D)` = keys of `D` ending in `_ref`, and `F` = the chip's
// `data-field` values —
//
//   1. containment:   F ⊇ (R ∪ references(D)) ∩ K
//   2. groundedness:  F ⊆ K
//
// This file checks the *model's* field set. `components.test.tsx` checks that
// the DOM's `data-field` nodes are exactly that set, which is what closes the
// loop the gate reads. The e2e (§14) runs the same predicate against a real
// engine's results on a real fixture project; this runs it against recorded
// ones, which is what makes it a component test rather than a second e2e.
//
// `R` is taken as the **union** over the schema's `oneOf` result branches. That
// is stricter than any single branch — a doc satisfying the union satisfies
// whichever branch it actually validates against — so passing here is a stronger
// statement than the gate's, not a weaker one.

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { readToolCall, readToolResult } from "../../src/api/events";
import { parseToolResult, referenceFields } from "../../src/stream/toolResult";
import { groupRows, historicalItem } from "../../src/stream/transcript";
import { allHistoryFrames, fixture, repoRoot } from "./fixture";

interface SchemaBranch {
  readonly required?: readonly string[];
}
interface ToolSchema {
  readonly result?: { readonly oneOf?: readonly SchemaBranch[]; readonly required?: readonly string[] };
}

/** `R`: the union of the required output fields over every result branch. */
function requiredOutputFields(tool: string): ReadonlySet<string> {
  const path = join(repoRoot, "schemas", "tools", `${tool}.schema.json`);
  const schema = JSON.parse(readFileSync(path, "utf8")) as ToolSchema;
  const result = schema.result;
  if (result === undefined) return new Set();
  const branches = result.oneOf ?? [result];
  const out = new Set<string>();
  for (const branch of branches) for (const field of branch.required ?? []) out.add(field);
  return out;
}

function chips(): {
  tool: string;
  fields: readonly string[];
  keys: readonly string[];
  parsed: boolean;
}[] {
  const items = allHistoryFrames().map((frame) => historicalItem(frame, fixture.session_id));
  const rows = groupRows(items);
  const out: { tool: string; fields: readonly string[]; keys: readonly string[]; parsed: boolean }[] =
    [];
  for (const row of rows) {
    if (row.row !== "chip" && row.row !== "ask") continue;
    const result = row.result;
    if (result === null) continue;
    const payload = readToolResult(result.payload);
    if (payload === null) continue;
    const tool =
      row.row === "chip" ? row.toolName : (readToolCall(row.call?.payload)?.name ?? "ask_user");
    const parsed = parseToolResult(payload.text);
    out.push({
      tool,
      fields: parsed.state === "parsed" ? parsed.fields : [],
      keys: parsed.state === "parsed" ? Object.keys(parsed.doc) : [],
      parsed: parsed.state === "parsed",
    });
  }
  return out;
}

describe("§7.2's completeness and groundedness predicate", () => {
  it("has chips to check, over more than one tool", () => {
    const found = chips();
    expect(found.length).toBeGreaterThan(3);
    expect(new Set(found.map((chip) => chip.tool)).size).toBeGreaterThan(3);
  });

  it("contains every present required field and every present reference", () => {
    for (const chip of chips()) {
      if (!chip.parsed) continue;
      const keys = new Set(chip.keys);
      const required = requiredOutputFields(chip.tool);
      const expected = new Set(
        [...required, ...referenceFields(chip.keys)].filter((field) => keys.has(field)),
      );
      for (const field of expected) {
        expect(chip.fields, `${chip.tool} must render ${field}`).toContain(field);
      }
    }
  });

  it("names no field the payload does not carry", () => {
    for (const chip of chips()) {
      const keys = new Set(chip.keys);
      for (const field of chip.fields) {
        expect(keys, `${chip.tool} must not invent ${field}`).toContain(field);
      }
    }
  });

  it("renders build_part's refs, which are the §7.2 example's own fields", () => {
    const build = chips().find((chip) => chip.tool === "build_part");
    expect(build?.fields).toContain("artifact_ref");
    expect(build?.fields).toContain("project_snapshot_ref");
    expect(build?.fields).toContain("status");
  });
});

describe("the named failure mode", () => {
  it("degrades visibly when the result text is not JSON", () => {
    const parsed = parseToolResult("distance: 12.5 mm");
    expect(parsed.state).toBe("unparsed");
    if (parsed.state === "unparsed") expect(parsed.reason).toBe("not_json");
  });

  it("degrades when the result parses to something that has no fields", () => {
    expect(parseToolResult("[1,2,3]")).toMatchObject({ state: "unparsed", reason: "not_an_object" });
    expect(parseToolResult('"a string"')).toMatchObject({
      state: "unparsed",
      reason: "not_an_object",
    });
    expect(parseToolResult("   ")).toMatchObject({ state: "unparsed", reason: "empty" });
  });

  it("degrades when two content blocks were concatenated into one text", () => {
    // §7.2 names "the result arrives as multiple content blocks" as the other
    // half of the failure mode. `normalizeEntries` joins text blocks, and two
    // concatenated JSON documents do not parse — so the same branch covers it
    // without the client having to guess at block counts.
    const joined = `${JSON.stringify({ status: "ok" })}${JSON.stringify({ status: "ok" })}`;
    expect(parseToolResult(joined).state).toBe("unparsed");
  });

  it("reports zero fields for the recorded unparseable result", () => {
    const measure = chips().find((chip) => chip.tool === "measure");
    expect(measure?.parsed).toBe(false);
    expect(measure?.fields).toEqual([]);
  });
});
