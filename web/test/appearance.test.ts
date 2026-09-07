// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The appearance store (INTERFACE.md §3.11, §5.5).
//
// Two properties: defaults are the authored picture, and the store is not
// workspace state. Assertions are on fields, never on wording.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it } from "vitest";
import {
  APPEARANCE_TOGGLES,
  AppearanceStore,
  DEFAULT_APPEARANCE,
  appearanceStore,
} from "../src/state/appearance";
import { DEFAULT_STATE, encodeWorkspaceUrl } from "../src/state/workspace";

afterEach(() => {
  appearanceStore.reset();
});

describe("appearance defaults are §3.11's authored picture", () => {
  it("starts shaded, orthographic, grid and triad on, override on", () => {
    expect(DEFAULT_APPEARANCE).toEqual({
      wireframe: false,
      ortho: true,
      grid: true,
      triad: true,
      materialOverride: true,
    });
    expect(new AppearanceStore().getSnapshot()).toEqual(DEFAULT_APPEARANCE);
  });

  it("exposes exactly the five toggles — Fit is an action, not a flag", () => {
    expect(APPEARANCE_TOGGLES).toEqual([
      "wireframe",
      "ortho",
      "grid",
      "triad",
      "materialOverride",
    ]);
    expect(APPEARANCE_TOGGLES).not.toContain("fit");
  });
});

describe("the appearance store", () => {
  it("toggles one field and leaves the others", () => {
    const store = new AppearanceStore();
    store.toggle("wireframe");
    expect(store.getSnapshot().wireframe).toBe(true);
    expect(store.getSnapshot().ortho).toBe(true);
    store.toggle("grid");
    expect(store.getSnapshot().grid).toBe(false);
    expect(store.getSnapshot().wireframe).toBe(true);
  });

  it("notifies once per real change and never on a no-op reset", () => {
    const store = new AppearanceStore();
    let notifications = 0;
    const stop = store.subscribe(() => {
      notifications += 1;
    });
    store.toggle("triad");
    store.toggle("triad");
    store.reset();
    expect(notifications).toBe(2);
    store.reset();
    expect(notifications).toBe(2);
    stop();
    store.toggle("ortho");
    expect(notifications).toBe(2);
  });

  it("is not written into the workspace URL — §4.5 stays closed", () => {
    const url = encodeWorkspaceUrl(DEFAULT_STATE);
    expect(url).not.toContain("wireframe");
    expect(url).not.toContain("ortho");
    expect(url).not.toContain("material");
    expect(url).not.toMatch(/[?&]grid=/);
    expect(url).not.toContain("triad");
  });
});

/*
 * J-web-viewport-6 — **verdict: by design**, pinned so a future pass does not
 * "fix" it.
 *
 * The audit filed "appearance and visibility toggles reset on reload" as an
 * inconsistency with everything else that survives one. It is the contract:
 * §5.5 says the cluster is *not* workspace state and that §4.5's record stays
 * closed, because a link that silently hid the floor would be a link that showed
 * a different instrument than the one it names. The URL half was already pinned
 * above; these are the two halves the ledger names as worth adding — the
 * STORAGE half, and a key-set assertion in BOTH directions so no appearance key
 * can be added to the serialized record, or a record field quietly answered from
 * here, without failing a test.
 */
describe("appearance is session-local by contract, not by omission (J-web-viewport-6)", () => {
  it("toggling every flag persists nothing", () => {
    window.sessionStorage.clear();
    const store = new AppearanceStore();
    for (const toggle of APPEARANCE_TOGGLES) store.toggle(toggle);
    // Also through the shipped singleton, which is what the cluster drives: a
    // store that persisted would do it there, not in a fresh instance.
    for (const toggle of APPEARANCE_TOGGLES) appearanceStore.toggle(toggle);
    expect(window.sessionStorage.length).toBe(0);
    // Non-vacuity: this harness CAN see a write, so the zero above is an
    // observation and not a blind spot.
    window.sessionStorage.setItem("probe", "1");
    expect(window.sessionStorage.length).toBe(1);
    window.sessionStorage.clear();
  });

  it("names no persistence API at all, which is the durable form of the rule", () => {
    // The runtime assertion above can only see the APIs this environment
    // provides; this one sees the module. §5.5's rule is that the cluster is
    // not workspace state and not a stored preference, so the source may not
    // reach for a store at all.
    const source = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "src", "state", "appearance.ts"), "utf8");
    for (const api of ["localStorage", "sessionStorage", "indexedDB", "document.cookie"]) {
      expect(source, `appearance.ts reaches for ${api}`).not.toContain(api);
    }
  });

  it("toggling changes no serialized workspace field", () => {
    const before = encodeWorkspaceUrl(DEFAULT_STATE);
    for (const toggle of APPEARANCE_TOGGLES) appearanceStore.toggle(toggle);
    expect(encodeWorkspaceUrl(DEFAULT_STATE)).toBe(before);
  });

  it("the two key sets are disjoint in both directions", () => {
    const serialized = new Set(Object.keys(DEFAULT_STATE));
    const appearance = new Set<string>(APPEARANCE_TOGGLES);
    // No appearance key may be added to §4.5's record …
    for (const key of appearance) expect(serialized.has(key)).toBe(false);
    // … and no record field may be answered from this store.
    for (const key of serialized) expect(appearance.has(key)).toBe(false);
  });
});
