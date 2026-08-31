// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The appearance store (INTERFACE.md §3.11, §5.5).
//
// Two properties: defaults are the authored picture, and the store is not
// workspace state. Assertions are on fields, never on wording.

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
