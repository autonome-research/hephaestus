// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The empty viewport is quiet (INTERFACE.md §5, §5.5; operator review 2026-09-01).
//
// The shipped well painted its whole control frame over every state, so an
// unbuilt part got a view cube, an axis triad, a grid readout describing a grid
// that was not drawn, six appearance toggles, an explode slider, a section
// control and a centred paragraph — nine surfaces addressing an artifact that is
// not there. Two assertions hold the fix:
//
// * **No geometry, no furniture.** jsdom gives the canvas no WebGL context, so a
//   mounted `Viewport` lands in `no-webgl` — a state with nothing on the canvas —
//   and every overlay selector is absent while the named absence is present.
// * **One short empty state.** `ViewportAbsence` is exported so all seven states
//   can be checked without a GL context: the two whose title IS the whole fact
//   print no prose, and the four that carry information the title does not keep it.
//
// No assertion is on a string of UI copy (§3): the prose cases are asserted as
// *presence of a body*, and the two title-only cases as its absence.

import { describe, expect, it, afterEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { Viewport, ViewportAbsence } from "../src/components/stage/viewport/Viewport";
import { ExplodeSlider } from "../src/components/stage/viewport/ExplodeSlider";
import { DEFAULT_STATE } from "../src/state/workspace";
import { workspaceStore } from "../src/state/react";

/** Every overlay the well used to paint over an empty canvas. */
const FURNITURE = [
  "[data-appearance]",
  "[data-appearance-control]",
  "[data-view-cube]",
  "[data-axis-triad]",
  "[data-grid-readout]",
  "[data-explode-t]",
  "[data-section-control]",
] as const;

describe("Viewport — an empty well carries one state and no controls", () => {
  let mounted: { host: HTMLElement; root: Root } | null = null;

  afterEach(() => {
    if (mounted !== null) {
      const live = mounted;
      act(() => {
        live.root.unmount();
      });
      live.host.remove();
      mounted = null;
    }
    workspaceStore.reset(DEFAULT_STATE);
  });

  function mount(): HTMLElement {
    workspaceStore.reset({ ...DEFAULT_STATE, artifact_ref: null });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => {
      root.render(
        <QueryClientProvider client={client}>
          <Viewport />
        </QueryClientProvider>,
      );
    });
    mounted = { host, root };
    return host;
  }

  it("names the state it is in and paints no overlay around it", () => {
    const host = mount();
    const well = host.querySelector('[data-testid="viewport"]');
    expect(well?.getAttribute("data-glb-state")).not.toBe("ready");
    expect(host.querySelector("[data-viewport-absence]")).not.toBeNull();
    for (const selector of FURNITURE) {
      expect(host.querySelector(selector), selector).toBeNull();
    }
  });

  it("keeps the canvas itself, because the well is the CAD surface (§5)", () => {
    const host = mount();
    expect(host.querySelector("[data-viewport-canvas]")).not.toBeNull();
  });
});

describe("ViewportAbsence — a title that is the whole fact is the whole state", () => {
  function plate(
    state: Parameters<typeof ViewportAbsence>[0]["state"],
    refusalReason: string | null = null,
  ): HTMLElement {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(
      <ViewportAbsence state={state} refusalReason={refusalReason} />,
    );
    return host;
  }

  /**
   * `EmptyState`'s prose container: icon, title `<p>`, then the body `<div>`, all
   * children of the `[data-density]` host. The body is the only `<div>` there.
   */
  function body(host: HTMLElement): Element | null {
    return host.querySelector("[data-viewport-absence] [data-density] > div");
  }

  it("prints no prose under `No artifact pinned` or `Loading geometry`", () => {
    for (const state of ["no-pin", "loading"] as const) {
      const host = plate(state);
      expect(host.querySelector("[data-viewport-absence]")?.getAttribute("data-viewport-absence")).toBe(
        state,
      );
      // A heading and nothing else: the title said it.
      expect(host.querySelectorAll("p")).toHaveLength(1);
      expect(body(host)).toBeNull();
    }
  });

  it("keeps the prose for every state whose title is not the whole fact", () => {
    for (const state of ["stale", "refused", "no-webgl", "empty"] as const) {
      const host = plate(state);
      expect(host.querySelectorAll("p").length, state).toBeGreaterThan(1);
      expect(body(host), state).not.toBeNull();
    }
  });

  it("still shows a refusal reason on a state that would otherwise be title-only", () => {
    const host = plate("no-pin", "malformed_gltf");
    expect(host.querySelector('[data-refusal-reason="malformed_gltf"]')).not.toBeNull();
  });
});

describe("ExplodeSlider — a 1-solid sheet starts collapsed (#60)", () => {
  afterEach(() => {
    workspaceStore.reset(DEFAULT_STATE);
  });

  it("keeps data-explode-t and hides the slider when explode cannot separate anything", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(<ExplodeSlider noop />);
    expect(host.querySelector("[data-explode-t]")?.getAttribute("data-explode-t")).toBe("0");
    expect(host.querySelector("[data-explode-collapsed]")).not.toBeNull();
    expect(host.querySelector("[data-testid='explode-slider']")).toBeNull();
    expect(host.querySelector("[data-explode-disclose]")).not.toBeNull();
  });

  it("shows the slider when explode can separate solids", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(<ExplodeSlider />);
    expect(host.querySelector("[data-explode-collapsed]")).toBeNull();
    expect(host.querySelector("[data-testid='explode-slider']")).not.toBeNull();
  });
});
