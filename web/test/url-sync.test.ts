// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, it, vi } from "vitest";
import { startUrlSync } from "../src/state/react";
import { DEFAULT_STATE, encodeWorkspaceUrl, WorkspaceStore } from "../src/state/workspace";

it("replays deep links/Back/Forward without authoring new entries; next part navigation still pushes", () => {
  const initial = { ...DEFAULT_STATE, part: "tread", session: "owned", inspector_tab: "checks" as const };
  window.history.replaceState(null, "", encodeWorkspaceUrl(initial));
  const store = new WorkspaceStore();
  const stop = startUrlSync(store);
  const push = vi.spyOn(window.history, "pushState");
  expect(store.getSnapshot()).toEqual(initial);
  const other = { ...initial, part: "riser" };
  window.history.replaceState(null, "", encodeWorkspaceUrl(other));
  window.dispatchEvent(new PopStateEvent("popstate"));
  window.dispatchEvent(new HashChangeEvent("hashchange"));
  expect(store.getSnapshot()).toEqual(other);
  expect(push).not.toHaveBeenCalled();
  store.update({ part: "third" });
  expect(push).toHaveBeenCalledTimes(1);
  stop(); push.mockRestore();
});
