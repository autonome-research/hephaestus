// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Meta-copy length (INTERFACE.md §7.4(d), §8(d), §7A.10(f), amended 2026-09-01).
//
// The measurement §0.2b took: the Stream spent 40-56 word paragraphs explaining
// the *mechanism* of a state the operator could already see, in the same type
// role as the transcript it was interrupting. The ruling is not "write less" —
// it is that the resting path states the fact in one sentence and the paragraph
// moves to `title`, where a reader who wants the mechanism can ask for it.
//
// THE RULE IS A TEST BECAUSE PROSE GROWS. A length clause with no assertion is
// a clause that holds until the next paragraph looks short while it is being
// written. `≤25 words or one sentence, whichever binds first` is the wording of
// §7.4(d), so both halves are asserted here over every map the three clauses
// name.
//
// WHAT IS EXEMPT, AND WHY IT IS LISTED RATHER THAN INFERRED. §7.4(d): "the
// cause is never shortened away". §7A.10(f): the §7A.5 lost-POST statement, the
// §7A.8 `cause` vocabulary and every disabled *reason* are exempt — they are
// the exceptional path, and the amendment shortens the resting path only. Each
// exemption below names its clause; an exemption that cannot name one is a
// string that has not been shortened yet.

import { describe, expect, it } from "vitest";
import { copy } from "../../src/copy";

/** §7.4(d)'s limit, both halves. */
const MAX_WORDS = 25;

function words(value: string): number {
  return value.trim().split(/\s+/u).length;
}

/**
 * Sentences, counted the way a reader counts them.
 *
 * A terminator followed by whitespace or the end of the string ends a
 * sentence; a trailing colon (`attachCause`, which introduces a path printed
 * beneath it) is not a terminator and those strings are exempt anyway.
 */
function sentences(value: string): number {
  return value.trim().split(/[.!?](?=\s|$)/u).filter((part) => part.trim() !== "").length;
}

function assertShort(label: string, value: string): void {
  expect(words(value), `${label}: ${String(words(value))} words — ${value}`).toBeLessThanOrEqual(
    MAX_WORDS,
  );
  expect(sentences(value), `${label}: more than one sentence — ${value}`).toBe(1);
}

function entries(label: string, map: Readonly<Record<string, string>>): [string, string][] {
  return Object.entries(map).map(([key, value]) => [`${label}.${key}`, value]);
}

describe("§7.4(d) — the stream's meta-copy is one sentence", () => {
  const named: [string, string][] = [
    ...entries("stateWhy", copy.stream.stateWhy),
    ...entries("runtimeFaultWhy", copy.stream.runtimeFaultWhy),
    ["runtimeFaultNext", copy.stream.runtimeFaultNext],
    ...entries("resync", copy.stream.resync),
    ["seamMidRun", copy.stream.seamMidRun],
    ...entries("turnOutcome", copy.stream.turnOutcome),
  ];

  it.each(named)("%s is ≤25 words and one sentence", (label, value) => {
    assertShort(label, value);
  });

  it("keeps `stateWhy` total over the closed vocabulary, `live` included", () => {
    // §7.4(d): "`stateWhy.live` is retained in `copy.ts` — a badge that does
    // not mount needs no tooltip, but the map stays total over the closed
    // vocabulary so a future state cannot land without copy."
    expect(Object.keys(copy.stream.stateWhy).sort()).toEqual([
      "detached",
      "historical",
      "live",
      "reconnecting",
      "resyncing",
    ]);
  });

  it("never shortens the cause away", () => {
    // The three-word verdicts, and `resync.gap`'s statement that the events
    // are NOT recovered, survive the cut. What was cut is the paragraph.
    expect(copy.stream.runtimeFault.process_down).toBe("runtime restarted");
    expect(copy.stream.runtimeFault.timeout).toBe("runtime not answering");
    expect(copy.stream.runtimeFault.unreachable).toBe("runtime unreachable");
    expect(copy.stream.resync.gap).toMatch(/not recovered/);
  });

  it("keeps the long form, on `title`, for every shortened tooltip", () => {
    // A sentence that replaced a paragraph and dropped it is not a move to
    // `title`, it is a deletion. Each detail below is what the well's fault
    // band and the resync break hang on `title`.
    for (const [label, value] of entries("runtimeFaultDetail", copy.stream.runtimeFaultDetail)) {
      expect(value, label).not.toBe("");
      expect(words(value), label).toBeGreaterThan(words(copy.stream.runtimeFaultWhy.timeout));
    }
    expect(Object.keys(copy.stream.runtimeFaultDetail).sort()).toEqual(
      Object.keys(copy.stream.runtimeFaultWhy).sort(),
    );
    expect(copy.stream.runtimeFaultNextDetail).toMatch(/twice/);
  });
});

describe("§8(d) — the named absences are one sentence each, and stay", () => {
  it.each(entries("absence", copy.stream.absence))(
    "%s is ≤25 words and one sentence",
    (label, value) => {
      assertShort(label, value);
    },
  );

  it("keeps both named absences and their long form", () => {
    // "A notice deleted rather than shortened fails §8's absence rule and this
    // clause together."
    expect(Object.keys(copy.stream.absence).sort()).toEqual(["terminal", "user_prompt"]);
    expect(Object.keys(copy.stream.absenceDetail).sort()).toEqual(["terminal", "user_prompt"]);
    expect(copy.stream.absenceDetail.terminal).toMatch(/still open/);
  });

  it.each([
    ["historyFailed", copy.stream.historyFailed],
    ["historyTruncated", copy.stream.historyTruncated],
    ["seam", copy.stream.seam],
  ])("%s is ≤25 words and one sentence", (label, value) => {
    assertShort(label, value);
  });
});

describe("§7A.10(f) — the composer's resting copy is one sentence", () => {
  /**
   * §7A.10(f)'s exemptions, each with the clause that grants it. The
   * exceptional path is allowed its paragraph; the resting path is not.
   */
  const EXEMPT: readonly string[] = [
    "sendUnknown", // §7A.5's lost-POST statement, exempt by name.
    "cancelNoRun", // A disabled reason (§7A.10's `unavailable` cause).
    "cancelNoStream", // A disabled reason.
    "cancelIdle", // A disabled reason.
    "attachHow", // §7A.8's remedy, printed beside the cause it belongs to.
  ];

  const resting: [string, string][] = Object.entries(
    copy.composer as Readonly<Record<string, unknown>>,
  )
    .filter(([key, value]) => typeof value === "string" && !EXEMPT.includes(key))
    .map(([key, value]) => [key, value as string]);

  it.each(resting)("%s is ≤25 words and one sentence", (label, value) => {
    assertShort(label, value);
  });

  it("exempts the exceptional path by name, and no more than that", () => {
    // The list is closed on purpose: a new long string cannot join it by
    // being long. Every exemption is a key that still exists.
    for (const key of EXEMPT) {
      expect(Object.keys(copy.composer), key).toContain(key);
    }
    expect(words(copy.composer.sendUnknown)).toBeGreaterThan(MAX_WORDS);
  });

  it("keeps every disabled reason and every attach cause, unshortened", () => {
    // §7A.10(f): "every disabled *reason*" is exempt, and §7A.8's causes are
    // the state that produced a product review finding.
    expect(Object.keys(copy.composer.disabled).sort()).toEqual([
      "agent_unavailable",
      "no_session",
      "run_in_flight",
    ]);
    for (const value of Object.values(copy.composer.attachCause)) {
      expect(value).not.toBe("");
    }
  });
});
