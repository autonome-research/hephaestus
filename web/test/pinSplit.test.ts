// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// J-web-viewport-9 — §4.1's "every panel below inherits that marking" had no
// consumer at all: the shell minted `data-pin-mode` and nothing below the
// header read it. `pinSplit` (`src/state/pinSplit.ts`) is the predicate the
// marker components now share; this pins its four exclusions, table-driven,
// because the fix note is explicit that "none of them is a 'probably'".

import { describe, expect, it } from "vitest";
import { pinSplit } from "../src/state/pinSplit";

describe("pinSplit — the four exclusions (J-web-viewport-9)", () => {
  it("names the split when the pin is held on a different part than the one selected", () => {
    expect(pinSplit("pinned", "bracket", "kerf_card")).toEqual({
      heldPart: "bracket",
      selectedPart: "kerf_card",
    });
  });

  it.each([
    ["not held — current follows publication, so the two axes cannot disagree", "current", "bracket", "kerf_card"],
    ["no source part known — a pasted URL can hold a ref without saying which part minted it", "pinned", null, "kerf_card"],
    ["nothing selected — there is no second axis to disagree with", "pinned", "bracket", null],
    ["the two agree — the negative half", "pinned", "bracket", "bracket"],
  ] as const)("returns null: %s", (_label, pinMode, heldPart, selectedPart) => {
    expect(pinSplit(pinMode, heldPart, selectedPart)).toBeNull();
  });

  it("returns null when neither the held part nor the selected part is known", () => {
    // Not one of the four exclusions named in the doc comment individually, but
    // the conjunction of two of them, and worth pinning: a `pinned` mode with
    // both axes unknown must not synthesize a split from nothing.
    expect(pinSplit("pinned", null, null)).toBeNull();
  });
});
