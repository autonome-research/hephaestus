// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The workspace state module's two invariants (INTERFACE.md §4.5):
//
//   1. the pin has exactly ONE authority, and a published build never advances
//      a held pin;
//   2. the closed record round-trips through the URL without loss.
//
// These are the two properties §3 gave as the reason for hand-rolling the store
// instead of taking a state library, so they are the two properties that get
// asserted. Nothing here asserts a string of UI copy: §3 forbids tests on
// wording, and every assertion below is on a field or a value.

import { describe, expect, it } from "vitest";
import {
  DEFAULT_STATE,
  INSPECTOR_TABS,
  PinAuthorityError,
  STAGE_TABS,
  WorkspaceStore,
  clampExplode,
  decodeWorkspaceUrl,
  effectiveInspectorTab,
  encodeWorkspaceUrl,
  inspectorTabsFor,
  isView,
  sameState,
  type WorkspaceState,
} from "../src/state/workspace";
import { copy } from "../src/copy";

const A = "artifact:build:sha256:" + "a".repeat(64);
const B = "artifact:build:sha256:" + "b".repeat(64);

/** Every field non-default, so a dropped one cannot hide behind a default. */
const FULL: WorkspaceState = {
  part: "stair",
  artifact_ref: A,
  pin_mode: "pinned",
  view: "az30_el-15",
  channel_overlay: "section",
  explode_t: 0.375,
  section_plane: "+Z@12.5",
  selection: {
    selection_id: "sel-9",
    kind: "face",
    bundle_ref: "artifact:selection-bundle:sha256:" + "c".repeat(64),
  },
  measure: { a: "sel-1", b: "sel-2" },
  stage_tab: "diff",
  inspector_tab: "provenance",
  focus: "stair_tread",
  session: "web:0123456789abcdef",
};

describe("the pin authority", () => {
  it("refuses to let update() write either pin field", () => {
    const store = new WorkspaceStore();
    // The patch type excludes them at compile time; the throw is for the
    // callers TypeScript does not see. Both doors, one rule.
    expect(() => {
      (store.update as (patch: Record<string, unknown>) => void)({ artifact_ref: A });
    }).toThrow(PinAuthorityError);
    expect(() => {
      (store.update as (patch: Record<string, unknown>) => void)({ pin_mode: "pinned" });
    }).toThrow(PinAuthorityError);
    expect(store.getSnapshot().artifact_ref).toBeNull();
  });

  it("adopts current while following, because nothing is held", () => {
    const store = new WorkspaceStore();
    store.observeCurrent(A);
    expect(store.getSnapshot().artifact_ref).toBe(A);
    expect(store.getSnapshot().pin_mode).toBe("current");
  });

  it("never advances a held pin when a new build becomes current", () => {
    // G5.6, stated as a unit test: render A, publish B, and the pin is still A.
    const store = new WorkspaceStore();
    store.observeCurrent(A);
    store.hold(A);
    store.observeCurrent(B);
    expect(store.getSnapshot().artifact_ref).toBe(A);
    expect(store.getSnapshot().pin_mode).toBe("pinned");
  });

  it("discards the selection and the measurement when following current again", () => {
    // §4.5: "Follow current" is offered "as an explicit one-click action that
    // states what it will discard" — so it must actually discard it. A
    // selection resolved against A does not mean anything against B.
    const store = new WorkspaceStore(FULL);
    store.followCurrent(B);
    const state = store.getSnapshot();
    expect(state.artifact_ref).toBe(B);
    expect(state.pin_mode).toBe("current");
    expect(state.selection).toBeNull();
    expect(state.measure).toBeNull();
    // Everything that is not about the artifact survives.
    expect(state.part).toBe(FULL.part);
    expect(state.view).toBe(FULL.view);
  });

  it("notifies subscribers once per real change and never on a no-op", () => {
    const store = new WorkspaceStore();
    let notifications = 0;
    const stop = store.subscribe(() => {
      notifications += 1;
    });
    store.update({ stage_tab: "script" });
    store.update({ stage_tab: "script" });
    store.observeCurrent(null);
    expect(notifications).toBe(1);
    stop();
    store.update({ stage_tab: "diff" });
    expect(notifications).toBe(1);
  });
});

describe("URL serialization", () => {
  it("round-trips every field of the closed record", () => {
    const decoded = decodeWorkspaceUrl(encodeWorkspaceUrl(FULL));
    expect(decoded).toEqual(FULL);
    expect(sameState(decoded, FULL)).toBe(true);
  });

  it("round-trips the default record", () => {
    expect(decodeWorkspaceUrl(encodeWorkspaceUrl(DEFAULT_STATE))).toEqual(DEFAULT_STATE);
  });

  it("round-trips a held pin, which is the field G5.6 is about", () => {
    const held: WorkspaceState = { ...DEFAULT_STATE, artifact_ref: A, pin_mode: "pinned" };
    const url = encodeWorkspaceUrl(held);
    expect(url).toContain(encodeURIComponent(A));
    const back = decodeWorkspaceUrl(url);
    expect(back.artifact_ref).toBe(A);
    expect(back.pin_mode).toBe("pinned");
  });

  it("keeps the §4.5 shape: /p/{part} plus the named query keys", () => {
    const url = encodeWorkspaceUrl({ ...DEFAULT_STATE, part: "stair" });
    expect(url.startsWith("#/p/stair?")).toBe(true);
    const query = new URLSearchParams(url.slice(url.indexOf("?") + 1));
    expect(query.get("view")).toBe("iso");
    expect(query.get("t")).toBe("0.0");
    expect(query.get("tab")).toBe("viewport");
  });

  it("round-trips a partial measurement without inventing the missing half", () => {
    const half: WorkspaceState = { ...DEFAULT_STATE, measure: { a: "sel-1" } };
    const back = decodeWorkspaceUrl(encodeWorkspaceUrl(half));
    expect(back.measure).toEqual({ a: "sel-1" });
    // An empty measurement is a real state — measure mode with no clicks yet —
    // and is distinct from `null`, which is "not measuring".
    const empty: WorkspaceState = { ...DEFAULT_STATE, measure: {} };
    expect(decodeWorkspaceUrl(encodeWorkspaceUrl(empty)).measure).toEqual({});
    expect(decodeWorkspaceUrl(encodeWorkspaceUrl(DEFAULT_STATE)).measure).toBeNull();
  });

  it("round-trips the sourcing inspector tab", () => {
    const state: WorkspaceState = { ...DEFAULT_STATE, part: "tread", inspector_tab: "sourcing" };
    expect(decodeWorkspaceUrl(encodeWorkspaceUrl(state)).inspector_tab).toBe("sourcing");
  });

  it("round-trips the Timeline and Results stage tabs", () => {
    for (const tab of ["timeline", "results"] as const) {
      const state: WorkspaceState = { ...DEFAULT_STATE, part: "tread", stage_tab: tab };
      const back = decodeWorkspaceUrl(encodeWorkspaceUrl(state));
      expect(back.stage_tab).toBe(tab);
    }
  });

  it("omits the inspector Results tab when the stage is already Results", () => {
    expect(inspectorTabsFor("viewport")).toEqual(INSPECTOR_TABS);
    expect(inspectorTabsFor("script")).toEqual(INSPECTOR_TABS);
    expect(inspectorTabsFor("results")).toEqual([
      "properties",
      "provenance",
      "checks",
      "dfm",
      "export",
      "sourcing",
    ]);
    expect(inspectorTabsFor("results")).not.toContain("results");
  });

  it("does not mount inspector Results when the stage tab is Results", () => {
    expect(effectiveInspectorTab("viewport", "results")).toBe("results");
    expect(effectiveInspectorTab("results", "results")).toBe("properties");
    expect(effectiveInspectorTab("results", "checks")).toBe("checks");
  });

  it("does not show two tabs labelled Results at once", () => {
    // Inspector keeps "Results" (§4.1, §6). The stage tab that mounts the
    // same panel is labelled Geometry so Viewport + inspector Results is not
    // two tabs with the same word. #17's omit path still hides the inspector
    // tab when the stage *is* Results.
    expect(copy.inspector.tabs.results).toBe("Results");
    expect(copy.stage.tabs.results).not.toBe(copy.inspector.tabs.results);
    const viewportLabels = [
      ...STAGE_TABS.map((tab) => copy.stage.tabs[tab]),
      ...inspectorTabsFor("viewport").map((tab) => copy.inspector.tabs[tab]),
    ];
    expect(viewportLabels.filter((label) => label === "Results")).toHaveLength(1);
    expect(inspectorTabsFor("results").map((tab) => copy.inspector.tabs[tab])).not.toContain(
      "Results",
    );
  });

  it("falls back closed on a value outside a closed vocabulary", () => {
    // A URL is user input. An unknown tab does not widen the vocabulary and
    // does not throw the workspace away; it lands on the default.
    const state = decodeWorkspaceUrl("#/p/stair?tab=terminal&itab=logs&ov=xray&pin=maybe");
    expect(state.stage_tab).toBe("viewport");
    expect(state.inspector_tab).toBe("results");
    expect(state.channel_overlay).toBe("none");
    expect(state.pin_mode).toBe("current");
    expect(state.part).toBe("stair");
  });

  it("accepts exactly the render module's view vocabulary and grammar", () => {
    // §5.5: the view cube drives `view` through `STANDARD_VIEWS` "plus its
    // `az<deg>_el<deg>` grammar, so a view named in the UI is a view
    // `heph render` can reproduce".
    for (const view of ["iso", "+X", "-Z", "front", "az45_el35", "az-30_el-12.5"]) {
      expect(isView(view)).toBe(true);
      expect(decodeWorkspaceUrl(`#/?view=${encodeURIComponent(view)}`).view).toBe(view);
    }
    for (const view of ["isometric", "az45", "el35", "+W", "az45_el35_roll10"]) {
      expect(isView(view)).toBe(false);
      expect(decodeWorkspaceUrl(`#/?view=${encodeURIComponent(view)}`).view).toBe("iso");
    }
  });

  it("survives a part name that needs escaping", () => {
    const state: WorkspaceState = { ...DEFAULT_STATE, part: "sub/dir name" };
    expect(decodeWorkspaceUrl(encodeWorkspaceUrl(state)).part).toBe("sub/dir name");
  });

  it("clamps explode to 0..1 and round-trips what it clamps to", () => {
    // §5.2: the client applies `offset · t` and nothing else; `t` outside 0..1
    // would be a client-invented displacement.
    expect(clampExplode(-3)).toBe(0);
    expect(clampExplode(9)).toBe(1);
    expect(clampExplode(Number.NaN)).toBe(0);
    for (const t of [0, 0.25, 0.375, 1]) {
      const state: WorkspaceState = { ...DEFAULT_STATE, explode_t: t };
      expect(decodeWorkspaceUrl(encodeWorkspaceUrl(state)).explode_t).toBe(t);
    }
  });

  it("drops a malformed selection rather than half-decoding one", () => {
    // A selection is `{selection_id, kind, bundle_ref}` or it is nothing: a
    // partial selection would be a client-constructed selection, which §1's
    // closed list forbids outright.
    expect(decodeWorkspaceUrl("#/p/x?sel=only-an-id").selection).toBeNull();
    expect(decodeWorkspaceUrl("#/p/x?sel=id|face").selection).toBeNull();
  });

  it("ignores a section plane that is not the server's spelling", () => {
    expect(decodeWorkspaceUrl("#/p/x?sec=%2BZ%4012.5").section_plane).toBe("+Z@12.5");
    expect(decodeWorkspaceUrl("#/p/x?sec=diagonal").section_plane).toBeNull();
  });
});
