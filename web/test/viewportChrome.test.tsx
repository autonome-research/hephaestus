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
import { readoutGlyphs } from "../src/system/Input";
import { copy } from "../src/copy";

/** One stylesheet, comments stripped, read relative to `web/src`. */
function css(relative: string): string {
  return readFileSync(join(process.cwd(), "src", relative), "utf8").replace(
    /\/\*[\s\S]*?\*\//g,
    "",
  );
}
import { DEFAULT_STATE } from "../src/state/workspace";
import { workspaceStore } from "../src/state/react";
import { ISO_ELEVATION_DEG, viewAngles } from "../src/viewport/cameras";
// B-7's fix (docs/audit-2026-09-04-broken.md) puts the cube's hit inventory in
// this module. It does not exist yet — see `web/test/cubeTargets.test.ts` — so
// every test below that imports it is red until a later round lands it, and
// that failure to resolve fails the WHOLE file's import, not only these
// assertions. That is a known, accepted cost of testing red-first against the
// ledger's own fix design rather than against the shipped (wrong) mechanism.
import { projectTargets, targetName } from "../src/viewport/cubeTargets";

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
    // Reveal/focus conversation, never spatial "below" guidance or an implicit build.
    const body = host.querySelector("[data-density] > div")?.textContent ?? "";
    expect(body).toContain("conversation");
    expect(host.querySelector("[data-unbuilt-conversation]")?.textContent).toBe("Open conversation");
    expect(host.querySelector("[data-not-built-command]")?.textContent).toBe("heph build tread");
  });
});

describe("ViewCube — front joins the plate (§5.5 C19)", () => {
  /** Render the cube for one camera. The SERVER snapshot is always
      `DEFAULT_STATE`, so a non-default view needs a client mount. */
  function cubeAt(view: string): HTMLElement {
    workspaceStore.reset({ ...DEFAULT_STATE, view });
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => {
      root.render(<ViewCube />);
    });
    return host;
  }

  afterEach(() => {
    workspaceStore.reset(DEFAULT_STATE);
  });

  // AMENDED by B-7's implementing round, and the amendment is the fix's own
  // negative half: the cube draws EXACTLY the cells facing the viewer, so a
  // `data-view` is present when its target is drawn and absent when it is not.
  // At the default camera (`iso`, looking from `+++`) the `iso` corner is
  // toward the viewer and the `-Y` face is behind the cube; at `front` it is
  // the other way round. The shipped cube satisfied the old, unconditional
  // form of this assertion by drawing `Front` at EVERY azimuth — which is the
  // defect B-7 names, not compliance with C19.
  it("addresses the named views inside the ONE [data-view-cube] box, each where it is drawn", () => {
    const iso = cubeAt("iso");
    const cubes = iso.querySelectorAll("[data-view-cube]");
    expect(cubes).toHaveLength(1);
    expect(cubes[0]?.querySelector('[data-view="iso"]')).not.toBeNull();
    // Behind the cube at iso: not drawn, and so not addressable.
    expect(cubes[0]?.querySelector('[data-view="front"]')).toBeNull();

    const front = cubeAt("front");
    const plate = front.querySelector("[data-view-cube]");
    expect(plate?.querySelector('[data-view="front"]')).not.toBeNull();
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

describe("ViewCube — every hit region is addressed and matches its own projection (B-7)", () => {
  /** Mount with a given `view`, so the cube's own client-side azimuth/elevation apply. */
  function mountAt(view: string): HTMLElement {
    workspaceStore.reset({ ...DEFAULT_STATE, view });
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => {
      root.render(<ViewCube />);
    });
    return host;
  }

  afterEach(() => {
    workspaceStore.reset(DEFAULT_STATE);
  });

  it("mints data-view on EVERY button, not only front and iso", () => {
    const host = mountAt("iso");
    const buttons = [...host.querySelectorAll("button")];
    // Fifteen today (six faces, four edges, five corners — B-7's own count of
    // the shipped, incomplete table); twenty-six once the fix lands. Either
    // way, every button drawn must carry its own `data-view`.
    expect(buttons.length).toBeGreaterThan(0);
    for (const button of buttons) {
      expect(button.getAttribute("data-view"), button.outerHTML).not.toBeNull();
      expect(button.getAttribute("data-view")).not.toBe("");
    }
  });

  it("the set of data-view values equals what the projection says is visible at iso", () => {
    const host = mountAt("iso");
    const domViews = new Set(
      [...host.querySelectorAll("[data-view]")].map((el) => el.getAttribute("data-view") ?? ""),
    );
    const angles = viewAngles("iso") ?? { azimuth_deg: 45, elevation_deg: ISO_ELEVATION_DEG };
    const projected = projectTargets(angles.azimuth_deg, angles.elevation_deg);
    const expectedViews = new Set(
      projected.filter((target) => target.visible).map((target) => targetName(target.direction)),
    );
    expect(domViews).toEqual(expectedViews);
  });

  it("the set of data-view values equals what the projection says is visible at +X", () => {
    const host = mountAt("+X");
    const domViews = new Set(
      [...host.querySelectorAll("[data-view]")].map((el) => el.getAttribute("data-view") ?? ""),
    );
    const angles = viewAngles("+X")!;
    const projected = projectTargets(angles.azimuth_deg, angles.elevation_deg);
    const expectedViews = new Set(
      projected.filter((target) => target.visible).map((target) => targetName(target.direction)),
    );
    expect(domViews).toEqual(expectedViews);
  });

  it("data-cube-hit is drawn only from the three closed kinds", () => {
    const host = mountAt("iso");
    const kinds = [...host.querySelectorAll("[data-cube-hit]")].map((el) =>
      el.getAttribute("data-cube-hit"),
    );
    expect(kinds.length).toBeGreaterThan(0);
    for (const kind of kinds) {
      expect(["face", "edge", "corner"]).toContain(kind);
    }
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

describe("ExplodeSlider — a 1-solid sheet hides explode (issue 60, issue 113 leftover)", () => {
  afterEach(() => {
    workspaceStore.reset(DEFAULT_STATE);
  });

  it("unmounts explode when it cannot separate anything", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(<ExplodeSlider noop />);
    expect(host.querySelector("[data-explode-t]")).toBeNull();
    expect(host.querySelector("[data-explode-collapsed]")).toBeNull();
    expect(host.querySelector("[data-testid='explode-slider']")).toBeNull();
    expect(host.querySelector("[data-explode-disclose]")).toBeNull();
  });

  it("shows the slider when explode can separate solids", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(<ExplodeSlider />);
    expect(host.querySelector("[data-explode-collapsed]")).toBeNull();
    expect(host.querySelector("[data-testid='explode-slider']")).not.toBeNull();
  });
});

describe("SectionControl — a 1-solid sheet hides section (issue 113 leftover)", () => {
  afterEach(() => {
    workspaceStore.reset(DEFAULT_STATE);
  });

  it("unmounts section when there is no cut on a one-solid plate", () => {
    const host = document.createElement("div");
    host.innerHTML = renderToStaticMarkup(<SectionControl bounds={null} noop />);
    expect(host.querySelector("[data-section-control]")).toBeNull();
    expect(host.querySelector("[data-section-disclose]")).toBeNull();
    expect(host.querySelector("[data-testid='section-enable']")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// J-web-viewport-4 — the editable readout must show every glyph the control
// can produce, not a magic character count (§4.7, amended 2026-09-05).
// ---------------------------------------------------------------------------

describe("readoutGlyphs — sized for the widest value the control can produce", () => {
  it("holds a minimum of 4 (the '0.00' case) plus one for a sign that might appear", () => {
    expect(readoutGlyphs(0, 1, 0, 2)).toBe(5); // "0.00" is 4 glyphs, +1 for a sign.
  });

  it("grows to fit the widest of min, max and the current value", () => {
    // A 100mm section offset at 2dp: "-100.00" is 7 glyphs (the sign is real
    // here, since `min` itself is negative), +1 for the reserved sign slot.
    expect(readoutGlyphs(-100, 100, 0, 2)).toBe(8);
    expect(readoutGlyphs(-100, 100, -87.5, 2)).toBe(8);
  });

  it("grows for a typed OUT-OF-BOUNDS value — §10/G5.3's no-clamp rule means it must stay readable", () => {
    // A PARAMS slider never clamps; a rejected value the operator cannot read
    // is a refusal they cannot act on.
    expect(readoutGlyphs(0, 10, 12345, 2)).toBeGreaterThan(readoutGlyphs(0, 10, 5, 2));
  });

  it("ignores a non-finite candidate rather than producing NaN glyphs", () => {
    expect(Number.isFinite(readoutGlyphs(0, 100, NaN, 2))).toBe(true);
  });

  it("never regresses below the shipped 7ch default for the common min/max/value shape", () => {
    // The section offset's latent 6-7 glyph case, the one the shipped 40px
    // content box overflowed regardless of spin buttons.
    expect(readoutGlyphs(-50, 50, -49.99, 2)).toBeGreaterThanOrEqual(7);
  });
});

describe("the readout's box declares the widest-value width, a zero minimum, and no spin buttons (J-web-viewport-4)", () => {
  const input = css("system/Input.module.css");

  it("sizes width from --readout-glyphs rather than a fixed 7ch", () => {
    expect(input).toMatch(
      /\.readout\s*\{[^}]*width:\s*calc\(var\(--readout-glyphs,\s*7\)\s*\*\s*1ch/,
    );
    expect(input).not.toMatch(/\.readout\s*\{[^}]*width:\s*7ch/);
  });

  it("keeps a zero minimum so the readout can still shrink in a flex row", () => {
    expect(input).toMatch(/\.readout\s*\{[^}]*min-width:\s*0;?[^}]*\}/);
  });

  it("suppresses the native spin buttons, which made the box unmeasurable", () => {
    expect(input).toMatch(/appearance:\s*textfield/);
    expect(input).toMatch(/-moz-appearance:\s*textfield/);
    expect(input).toMatch(/::-webkit-(?:outer|inner)-spin-button/);
  });
});
