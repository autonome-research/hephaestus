// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// A tool result reads as a result (INTERFACE.md §7.2, §3.3).
//
// THE DEFECT THESE ASSERTIONS PIN. An operator ran one prompt against a
// `kerf_card` part session. `read_part` returned `ok`, and the chip rendered its
// result document as the wire format: a `part_param_state_hash` key and a
// 71-glyph `sha256:…` value, in `.code`, which sets `word-break: break-all` —
// and, because of the auto-placement bug fixed in `Transcript.module.css`, in a
// grid track that had resolved to zero width. The digest came out as a vertical
// stack of single letters. The layout half is a stylesheet fix asserted in
// `test/stream/chip.test.tsx`; this file is the reading half, which no
// stylesheet fixes: a successful call has an outcome, and 64 hex digits is not
// it.
//
// What is NOT asserted here is any particular sentence. §3's rule is that tests
// assert on fields and information content, never on wording, so the assertions
// below are about WHICH of the document's own keys reach the headline, that no
// key reaching it was invented, and that a digest is shortened rather than
// dropped.

import { describe, expect, it } from "vitest";
import {
  DIGEST_GLYPHS,
  SUMMARY_FIELDS_MAX,
  SUMMARY_VALUE_MAX,
  chipHeadline,
  displayValue,
  isOpaqueDigest,
  operandFromArgs,
  summaryOf,
} from "../../src/stream/toolSummary";
import { parseToolResult } from "../../src/stream/toolResult";

/** The result document the operator actually hit, as the sidecar serialises it. */
const READ_PART = JSON.stringify({
  status: "ok",
  part: "kerf_card",
  part_param_state_hash:
    "sha256:ad206068c29722297302d4fadb11c198d45356f4a95c31f0b8f9d4d6f1a2b3c4d",
  lines: 42,
});

describe("an opaque digest is recognised by SHAPE, never by key name", () => {
  it("knows the three forms the engine mints", () => {
    expect(
      isOpaqueDigest("sha256:ad206068c29722297302d4fadb11c198d45356f4a95c31f0b8f9d4d6f1a2b3c4d"),
    ).toBe(true);
    expect(
      isOpaqueDigest(
        "artifact:build:sha256:83f4822a7943a7baf11b29d15c8af23c341fb4c0bfff352ac44a3f67d4bac82b",
      ),
    ).toBe(true);
    // A bare hex run, which is how a `*_state_hash` reaches the transcript.
    expect(isOpaqueDigest("ad206068c29722297302d4fadb11c198d45356f4a95c31f0b8f9d4d6f1a2b3c4d")).toBe(
      true,
    );
  });

  it("does not mistake a readable value for one", () => {
    // The name of the key is irrelevant on purpose: a key called `hash` whose
    // value is `none` is readable, and a hash under an unexpected key is still
    // a hash. Testing the shape is what makes both true.
    for (const readable of ["ok", "none", "kerf_card", "12.5 mm", "parts/kerf_card.py", "1"]) {
      expect(isOpaqueDigest(readable), readable).toBe(false);
    }
  });
});

describe("a value is elided for reading and never destroyed", () => {
  it("keeps head and tail of a digest, and the whole value beside it", () => {
    const parsed = parseToolResult(READ_PART);
    expect(parsed.state).toBe("parsed");
    if (parsed.state !== "parsed") return;
    const shown = displayValue(parsed.doc["part_param_state_hash"]);
    expect(shown.elided).toBe(true);
    expect(shown.text.length).toBeLessThanOrEqual(DIGEST_GLYPHS);
    // The whole digest survives, which is what makes the elision a rendering
    // decision rather than a loss of an identity.
    expect(shown.full).toBe(parsed.doc["part_param_state_hash"]);
    expect(shown.full.length).toBeGreaterThan(shown.text.length);
    // Head AND tail: a bare tail slice collided on two different refs in the
    // shipped script status bar (§4.7), and two hashes that render alike are
    // worse than one that renders long.
    expect(shown.text.startsWith("sha256:")).toBe(true);
    expect(shown.full.endsWith(shown.text.slice(-8))).toBe(true);
  });

  it("leaves a short readable value exactly as the server sent it", () => {
    expect(displayValue("ok")).toEqual({ text: "ok", full: "ok", elided: false });
    expect(displayValue(42).text).toBe("42");
  });

  it("cuts a long structure without dressing it as a digest", () => {
    const findings = Array.from({ length: 60 }, (_, i) => ({ rule: `r${String(i)}` }));
    const shown = displayValue(findings);
    expect(shown.elided).toBe(true);
    expect(shown.text.length).toBeLessThan(shown.full.length);
    expect(shown.full).toContain("r59");
  });
});

describe("the headline is drawn from the document, never composed", () => {
  it("leads with the fields that answer what happened", () => {
    const parsed = parseToolResult(READ_PART);
    if (parsed.state !== "parsed") throw new Error("fixture does not parse");
    const summary = summaryOf(parsed.doc, parsed.fields);
    expect(summary.parts.map((part) => part.field)).toEqual(["part"]);
    expect(summary.parts.map((part) => part.value)).toEqual(["kerf_card"]);
    // The count is the document's own, so the disclosure below the headline can
    // be labelled without the chip recounting anything.
    expect(summary.fields).toBe(4);
  });

  it("never puts a digest on the headline", () => {
    const parsed = parseToolResult(READ_PART);
    if (parsed.state !== "parsed") throw new Error("fixture does not parse");
    const summary = summaryOf(parsed.doc, parsed.fields);
    for (const part of summary.parts) {
      expect(isOpaqueDigest(part.value), part.field).toBe(false);
      expect(part.value.length).toBeLessThanOrEqual(SUMMARY_VALUE_MAX);
    }
    expect(summary.parts.map((part) => part.field)).not.toContain("part_param_state_hash");
  });

  it("names only fields the document carries — groundedness, on the headline", () => {
    const doc = { artifact_ref: "artifact:build:sha256:abc123abc123abc123abc123abc123ab" };
    const summary = summaryOf(doc, Object.keys(doc));
    for (const part of summary.parts) expect(Object.keys(doc)).toContain(part.field);
  });

  it("stays one line: at most two fields, whatever the document's size", () => {
    const doc = { status: "ok", part: "a", name: "b", message: "c", reason: "d" };
    const summary = summaryOf(doc, Object.keys(doc));
    expect(summary.parts).toHaveLength(SUMMARY_FIELDS_MAX);
    expect(summary.fields).toBe(5);
  });

  it("falls back to the document's own order when it carries no headline field", () => {
    const doc = { solids: 3, genus: 9 };
    const summary = summaryOf(doc, Object.keys(doc));
    expect(summary.parts.map((part) => part.field)).toEqual(["solids", "genus"]);
  });

  it("prints NO headline rather than a guessed one when every value is opaque", () => {
    // §4.4's discipline: a summary that had to be invented is not a summary.
    // The chip renders a stated sentence about the absence and points at the
    // disclosure holding the identities.
    const doc = {
      artifact_ref: "artifact:build:sha256:83f4822a7943a7baf11b29d15c8af23c341fb4c0bfff352ac44a3",
      project_snapshot_ref: "artifact:snapshot:sha256:aa11bb22cc33dd44ee55ff6677889900aabbccdd",
    };
    const summary = summaryOf(doc, Object.keys(doc));
    expect(summary.parts).toEqual([]);
    expect(summary.fields).toBe(2);
  });

  it("does not headline a multi-line string", () => {
    const doc = { message: "line one\nline two" };
    expect(summaryOf(doc, Object.keys(doc)).parts).toEqual([]);
  });

  it("does not headline result metadata the operator already has on the badge", () => {
    const doc = { status: "ok", line_count: 65, truncated: false, generation: 3, current: true };
    expect(summaryOf(doc, Object.keys(doc)).parts).toEqual([]);
  });
});

describe("the chip face uses call arguments for the operand (#71, #48)", () => {
  it("reads the part from a running call that has no result document", () => {
    expect(operandFromArgs({ name: "tread" })).toEqual({ field: "name", value: "tread" });
    const running = chipHeadline({ args: { part: "kerf_card" } });
    expect(running.parts).toEqual([{ field: "part", value: "kerf_card" }]);
    expect(running.fields).toBe(0);
  });

  it("keeps that operand on ok when the result omitted part (#69)", () => {
    const doc = { status: "ok", line_count: 65, truncated: false };
    const summary = chipHeadline({
      args: { name: "kerf_card" },
      doc,
      fields: Object.keys(doc),
    });
    expect(summary.parts.map((part) => part.value)).toEqual(["kerf_card"]);
    expect(summary.parts.map((part) => part.field)).not.toContain("line_count");
    expect(summary.fields).toBe(3);
  });

  it("does not turn an argument into a result field", () => {
    const doc = { status: "ok" };
    const summary = chipHeadline({ args: { name: "tread" }, doc, fields: Object.keys(doc) });
    expect(summary.parts[0]?.value).toBe("tread");
    expect(Object.keys(doc)).not.toContain("name");
  });
});
