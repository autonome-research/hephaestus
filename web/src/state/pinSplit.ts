// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The split state: the stage is showing one part's artifact while the inspector
// is showing another's (INTERFACE.md §4.1, §4.5).
//
// §4.1 says the header "is visibly marked and every panel below inherits that
// marking", on the element it calls the most important in the document, "because
// G5.5/G5.6 are exactly the case where a user must not be able to forget which
// build they are looking at". What shipped was `Shell.tsx` minting
// `data-pin-mode` on the shell root with a comment reading "the attribute is the
// inheritance: any panel can style against it" — and that sentence is the whole
// defect (J-web-viewport-9). An attribute is a MECHANISM for inheritance, not
// the inheritance; a grep for it found six hits, three of them comments, two
// mints, and CSS scoped to the chip itself. Nothing below the header opted in,
// for the whole life of the workspace.
//
// **The marking is words, and it names what each region is showing.** Tinting
// every panel is the obvious patch and the wrong shape twice over: it marks all
// four regions identically when the actual fact is that two follow the PIN (the
// stage and the export control) and two follow the SELECTION (the inspector and
// the script tab), and it would make colour the sole carrier of a fact, which
// §3.13.2 forbids.
//
// **And a marker that is always on is not a marking.** Both markers mount only
// while the two axes disagree — which is exactly the condition the header chip
// already computes, so this module is where that condition now lives once.

/** The two parts a split names, in the order the reader meets them. */
export interface PinSplitState {
  /** The part whose held artifact the STAGE and the export control are showing. */
  readonly heldPart: string;
  /** The part the rail has selected, which the INSPECTOR and Script follow. */
  readonly selectedPart: string;
}

/**
 * The split, or `null` when there is none.
 *
 * Four exclusions, and none of them is a "probably":
 *
 * 1. not held — `current` follows publication and both axes are the same part;
 * 2. no source part known — a pasted URL can hold a reference without saying
 *    which part minted it, and a marker that guesses is worse than none;
 * 3. nothing selected — there is no second axis to disagree with;
 * 4. the two agree — the negative half. A marker on every held pin would train
 *    the reader to ignore it before the one time it matters.
 */
export function pinSplit(
  pinMode: string,
  heldPart: string | null,
  selectedPart: string | null,
): PinSplitState | null {
  if (pinMode !== "pinned") return null;
  if (heldPart === null || selectedPart === null) return null;
  if (heldPart === selectedPart) return null;
  return { heldPart, selectedPart };
}
