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

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it, afterEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import {
  Viewport,
  ViewportAbsence,
  emptyPinAbsence,
} from "../src/components/stage/viewport/Viewport";
import { ExplodeSlider } from "../src/components/stage/viewport/ExplodeSlider";
import { SectionControl } from "../src/components/stage/viewport/SectionControl";
import { ViewCube } from "../src/components/stage/viewport/ViewCube";
import { copy } from "../src/copy";
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
    const canvas = host.querySelector<HTMLCanvasElement>("[data-viewport-canvas]");
    expect(canvas).not.toBeNull();
    expect(canvas?.tabIndex).toBe(0);
    expect(canvas?.id).toBe("stage");
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

describe("the not-built absence — §5.5 C10, both halves of the never-renders rule", () => {
  it("composes to not-built ONLY when a part is selected AND its build state is not_built", () => {
    expect(emptyPinAbsence("tread", "not_built")).toBe("not-built");
    // The negative half, case by case: no selection, a failed build, an
    // unanswered projection — every one stays `no-pin`, never `not-built`.
    expect(emptyPinAbsence(null, "not_built")).toBe("no-pin");
    expect(emptyPinAbsence("tread", "error")).toBe("no-pin");
    expect(emptyPinAbsence("tread", "ok")).toBe("no-pin");
    expect(emptyPinAbsence("tread", undefined)).toBe("no-pin");
  });

  it("names the part in the title and carries exactly the two remedies in the body", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(
      <ViewportAbsence state="not-built" refusalReason={null} part="tread" />,
    );
    expect(host.querySelector('[data-viewport-absence="not-built"]')).not.toBeNull();
    // The title names the part — a server fact, composed not derived.
    const title = host.querySelector("[data-density] > p")?.textContent ?? "";
    expect(title).toContain("tread");
    // Remedy one: the agent below. Remedy two: the CLI command, in `.code`.
    const body = host.querySelector("[data-density] > div")?.textContent ?? "";
    expect(body).toContain("agent");
    expect(host.querySelector("[data-not-built-command]")?.textContent).toBe("heph build tread");
  });
});

describe("ViewCube — front joins the plate (§5.5 C19)", () => {
  it("renders the named-views row inside the ONE [data-view-cube] box", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(<ViewCube />);
    const cubes = host.querySelectorAll("[data-view-cube]");
    expect(cubes).toHaveLength(1);
    // `front` — the one named view — is inside the same bounding box as the
    // orientation cross, not a free-floating control beside it.
    expect(cubes[0]?.querySelector('[data-view="front"]')).not.toBeNull();
    expect(cubes[0]?.querySelector('[data-view="iso"]')).not.toBeNull();
  });

  it("is a 3D cube in the tab order with an accessible name; axis buttons are gone", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(<ViewCube />);
    const cube = host.querySelector("[data-view-cube]");
    expect(cube?.getAttribute("tabindex")).toBe("0");
    expect(cube?.getAttribute("aria-label")).toBe(copy.viewport.viewCube.label);
    const labels = [...host.querySelectorAll("button")].map((button) => button.textContent ?? "");
    for (const axis of ["+Y", "+Z", "-X", "+X", "-Z", "-Y"]) {
      expect(labels).not.toContain(axis);
    }
  });

  it("cube glyphs spend ink-strong, never accent-ink on accent-quiet (§3.9, §3.13.1)", () => {
    // `--accent-ink` (#06121d) on `--accent-quiet` (#26374b) is 1.56:1.
    // The permit table allows `--accent-ink` only on `--accent`. The cube
    // selected state is an accent-quiet fill; its words stay `--ink-strong`.
    const css = readFileSync(
      join(process.cwd(), "src/components/stage/viewport/ViewCube.module.css"),
      "utf8",
    );
    expect(css).not.toMatch(/color:\s*var\(--accent-ink\)/);
    expect(css).toMatch(/color:\s*var\(--ink-strong\)/);
    expect(css).toMatch(/\[data-cube-current\][\s\S]*background:\s*var\(--accent-quiet\)/);
  });
});

describe("the bottom band yields in C18's fixed order (§5.5)", () => {
  afterEach(() => {
    workspaceStore.reset(DEFAULT_STATE);
  });

  it("explode collapses to its disclosure when yielded, and not otherwise", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(<ExplodeSlider yielded />);
    expect(host.querySelector("[data-explode-collapsed]")).not.toBeNull();
    expect(host.querySelector("[data-testid='explode-slider']")).toBeNull();

    const wide = document.createElement("div");
    wide.innerHTML = renderToStaticMarkup(<ExplodeSlider yielded={false} />);
    expect(wide.querySelector("[data-explode-collapsed]")).toBeNull();
    expect(wide.querySelector("[data-testid='explode-slider']")).not.toBeNull();
  });

  it("the section control folds to a disclosure when yielded, keeping the cut on the attribute", () => {
    // `renderToStaticMarkup` reads the SERVER snapshot (DEFAULT_STATE), so a
    // non-default plane needs a client mount.
    workspaceStore.reset({ ...DEFAULT_STATE, section_plane: "+Z@0" });
    const mountWith = (yielded: boolean): HTMLElement => {
      const host = document.createElement("div");
      document.body.appendChild(host);
      const root = createRoot(host);
      act(() => {
        root.render(<SectionControl bounds={null} yielded={yielded} />);
      });
      return host;
    };

    const host = mountWith(true);
    const control = host.querySelector("[data-section-yielded]");
    expect(control).not.toBeNull();
    // The band yields the CONTROL, never the cut.
    expect(control?.getAttribute("data-section-plane")).toBe("+Z@0");
    expect(host.querySelector("[data-testid='section-axis']")).toBeNull();
    expect(host.querySelector("[data-section-disclose]")).not.toBeNull();

    const wide = mountWith(false);
    expect(wide.querySelector("[data-section-yielded]")).toBeNull();
    expect(wide.querySelector("[data-testid='section-axis']")).not.toBeNull();
  });

  it("a yielded section control with NO cut collapses to its disclosure", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(<SectionControl bounds={null} yielded />);
    expect(host.querySelector("[data-section-yielded]")).toBeNull();
    expect(host.querySelector("[data-testid='section-enable']")).toBeNull();
    expect(host.querySelector("[data-section-disclose]")).not.toBeNull();
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
