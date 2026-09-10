// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// J-web-stream-2: §7.4(e)'s "a session exists and has no transcript" state
// (`stream/streamChrome.ts::showsEmptyTranscript`).
//
// The predicate is pure and has SIX exclusions, each of which already owns its
// own composed state and must not be shadowed by this one: no session
// selected, `agent_unavailable`, a runtime fault, the listing refused for any
// other reason, the history read not yet `complete`, and — only once every
// other exclusion clears — a non-zero row count. Table-driven over the six, so
// a future change that widens or narrows an exclusion is caught here rather
// than in a fixture that happens to reach one path.

import { describe, expect, it } from "vitest";
import { showsEmptyTranscript, type EmptyTranscript } from "../../src/stream/streamChrome";
import { emptyHistory } from "../../src/stream/history";

/** The one state where the predicate is true, absent an override below. */
function base(overrides: Partial<EmptyTranscript> = {}): EmptyTranscript {
  return {
    selected: "sess-1",
    unavailable: false,
    fault: null,
    listRefused: false,
    history: { ...emptyHistory(), state: "complete" },
    rows: 0,
    ...overrides,
  };
}

describe("showsEmptyTranscript — the six exclusions (§7.4(e))", () => {
  it("is true only when every exclusion clears and there are no rows", () => {
    expect(showsEmptyTranscript(base())).toBe(true);
  });

  it("1. no session selected — §7A.2 owns that state", () => {
    expect(showsEmptyTranscript(base({ selected: null }))).toBe(false);
  });

  it("2. agent_unavailable — the composer's §7A.8 refusal owns that cause", () => {
    expect(showsEmptyTranscript(base({ unavailable: true }))).toBe(false);
  });

  it("3. a runtime fault — the fault band owns that state", () => {
    expect(showsEmptyTranscript(base({ fault: "process_down" }))).toBe(false);
  });

  it("4. the session listing was refused for any other reason", () => {
    expect(showsEmptyTranscript(base({ listRefused: true }))).toBe(false);
  });

  it("5a. loading has its own visible status, not a true-empty claim (§8(b))", () => {
    expect(
      showsEmptyTranscript(base({ history: { ...emptyHistory(), state: "loading" } })),
    ).toBe(false);
  });

  it("5b. the history read failed — that has its own sentence", () => {
    expect(
      showsEmptyTranscript(base({ history: { ...emptyHistory(), state: "failed" } })),
    ).toBe(false);
  });

  it("5c. the history read is truncated — that has its own sentence", () => {
    expect(
      showsEmptyTranscript(base({ history: { ...emptyHistory(), state: "truncated" } })),
    ).toBe(false);
  });

  it("6. rows exist — there is a transcript", () => {
    expect(showsEmptyTranscript(base({ rows: 3 }))).toBe(false);
  });

  it("does not fire from row count alone if any earlier exclusion also applies", () => {
    // Combining two disqualifiers must not accidentally cancel back to true.
    expect(showsEmptyTranscript(base({ selected: null, unavailable: true }))).toBe(false);
    expect(showsEmptyTranscript(base({ fault: "timeout", listRefused: true }))).toBe(false);
  });
});
