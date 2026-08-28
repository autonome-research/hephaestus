// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The URL sync (INTERFACE.md §4.5): the hash is a *projection* of the store,
// never a second source of truth.

import { afterEach, describe, expect, it } from "vitest";
import { WorkspaceStore, decodeWorkspaceUrl } from "../src/state/workspace";
import { startUrlSync } from "../src/state/react";

let stop: (() => void) | null = null;

afterEach(() => {
  stop?.();
  stop = null;
});

describe("startUrlSync", () => {
  it("hydrates the store from the hash it is started with", () => {
    window.history.replaceState(null, "", "/#/p/stair?tab=script&itab=checks&view=%2BZ");
    const store = new WorkspaceStore();
    stop = startUrlSync(store);
    const state = store.getSnapshot();
    expect(state.part).toBe("stair");
    expect(state.stage_tab).toBe("script");
    expect(state.inspector_tab).toBe("checks");
    expect(state.view).toBe("+Z");
  });

  it("writes every store change back into the hash", () => {
    window.history.replaceState(null, "", "/#/p/stair");
    const store = new WorkspaceStore();
    stop = startUrlSync(store);
    store.update({ stage_tab: "diff" });
    expect(decodeWorkspaceUrl(window.location.hash).stage_tab).toBe("diff");
    store.hold("artifact:build:sha256:" + "d".repeat(64));
    const back = decodeWorkspaceUrl(window.location.hash);
    expect(back.pin_mode).toBe("pinned");
    expect(back.artifact_ref).toBe("artifact:build:sha256:" + "d".repeat(64));
  });

  it("adopts a hash the app did not author, which is Back/Forward", () => {
    window.history.replaceState(null, "", "/#/p/stair");
    const store = new WorkspaceStore();
    stop = startUrlSync(store);
    window.history.replaceState(null, "", "/#/p/bracket?tab=script");
    window.dispatchEvent(new HashChangeEvent("hashchange"));
    expect(store.getSnapshot().part).toBe("bracket");
    expect(store.getSnapshot().stage_tab).toBe("script");
  });
});
