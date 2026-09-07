// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// J-web-stream-12: `state/visibility.ts` builds its per-(part, label) key with
// an escaped `\u0000` separator, spelled once in `key()`, because a raw NUL
// byte in a source file is invisible in every editor, diff and — critically —
// `grep`. Two functions eight lines below the original key builder hand-built
// the per-part PREFIX with a raw byte instead of calling `key(part, "")`,
// breaking the module's own "spelled here and nowhere else" rule in its own
// file. `partPrefix`/`visibilityPartPrefix` is the fix: the one honest way to
// spell the prefix, used everywhere a prefix is needed.
//
// This is the guard the class needed: a name containing a space (a plausible
// part or label name) run through every prefix-building path, asserting they
// all agree with the key builder — so a caller that hand-builds a prefix again
// cannot silently drift from `key`.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  VisibilityStore,
  labelsForPart,
  visibilityKey,
  visibilityPartPrefix,
} from "../src/state/visibility";

describe("the key separator is spelled once, and every prefix agrees with it", () => {
  it("visibilityPartPrefix is exactly the key of an empty label", () => {
    // For a name containing a space, since a hand-built prefix historically
    // used a literal " " and would have matched this case coincidentally —
    // this is why the fixture name below is chosen to have a space in it.
    const part = "my part";
    expect(visibilityPartPrefix(part)).toBe(visibilityKey(part, ""));
  });

  it("the prefix uses the NUL escape as its separator, not a plain space", () => {
    // The historical defect: two independent readers each hand-built the
    // prefix as a literal space instead of calling this function, which looks
    // plausible for an unspaced part name and is provably wrong once a part
    // name contains a space of its own.
    const part = "my part";
    const prefix = visibilityPartPrefix(part);
    expect(prefix).not.toBe(part + " ");
    expect(prefix).toBe(part + "\u0000");
  });

  it("VisibilityStore.hiddenLabels and showAll use the same prefix as labelsForPart, for a spaced name", () => {
    const store = new VisibilityStore();
    const part = "left panel";
    const other = "right panel";
    store.toggle(part, "top edge");
    store.toggle(part, "bottom edge");
    store.toggle(other, "top edge");

    expect(store.hiddenLabels(part).slice().sort()).toEqual(["bottom edge", "top edge"]);
    expect(labelsForPart(store.getSnapshot(), part).slice().sort()).toEqual(
      store.hiddenLabels(part).slice().sort(),
    );

    store.showAll(part);
    expect(store.hiddenLabels(part)).toHaveLength(0);
    // The other part's entries, which share no separator ambiguity with a
    // hand-built space-joined prefix, must be untouched.
    expect(store.hiddenLabels(other)).toEqual(["top edge"]);
  });

  it("a part name that is a prefix of another part's name (once space-joined) does not collide", () => {
    // The exact failure a raw space (or any printable separator) invites:
    // "a" and "a b" would share the naive prefix "a " for label "b" of part
    // "a b" and label "" of part "a"... the NUL separator cannot occur in a
    // part name or label (§5.4), so this can never alias.
    const store = new VisibilityStore();
    store.toggle("a", "b");
    store.toggle("a b", "c");
    expect(store.hiddenLabels("a")).toEqual(["b"]);
    expect(store.hiddenLabels("a b")).toEqual(["c"]);
  });
});

describe("visibilityKey and visibilityPartPrefix are exported so a test never has to guess the byte", () => {
  it("labelsForPart(_, null) is empty without touching the key builder", () => {
    expect(labelsForPart(new Set(["x" + "\u0000" + "y"]), null)).toEqual([]);
  });
});

/*
 * J-web-viewport-6 — **verdict: by design**, pinned so a future pass does not
 * "fix" it.
 *
 * The module's own source states the sharper form of §5.5's rule: a link that
 * silently hid a solid would show a different model than it names, so a hidden
 * solid is session-local and dies with the tab. That is a decision, and a
 * decision with no test looks exactly like an omission to the next reader.
 */
describe("a hidden solid is session-local by contract (J-web-viewport-6)", () => {
  it("hiding and showing persists nothing", () => {
    window.sessionStorage.clear();
    const store = new VisibilityStore();
    store.toggle("tread", "top face");
    store.toggle("tread", "top face");
    store.toggle("tread", "bottom face");
    store.showAll("tread");
    expect(window.sessionStorage.length).toBe(0);
    // Non-vacuity: the harness CAN see a write.
    window.sessionStorage.setItem("probe", "1");
    expect(window.sessionStorage.length).toBe(1);
    window.sessionStorage.clear();
  });

  it("names no persistence API at all, which is the durable form of the rule", () => {
    const source = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "src", "state", "visibility.ts"), "utf8");
    for (const api of ["localStorage", "sessionStorage", "indexedDB", "document.cookie"]) {
      expect(source, `visibility.ts reaches for ${api}`).not.toContain(api);
    }
  });

  it("a fresh store starts with nothing hidden — the authored picture, every time", () => {
    const store = new VisibilityStore();
    expect(store.hiddenLabels("tread")).toEqual([]);
    expect(store.getSnapshot().size).toBe(0);
  });
});
