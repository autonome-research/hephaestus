// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The appearance cluster's markup contract (INTERFACE.md §3.11, §5.5).
//
// Assertions are on `data-*` attributes and pressed/disabled state, never on
// wording (§3). The cluster must exist without inventing a new inspector
// panel or a new icon id.

import { afterEach, describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";

import { ICON_IDS } from "../src/system";
import { AppearanceControls } from "../src/components/stage/viewport/AppearanceControls";
import { APPEARANCE_TOGGLES, appearanceStore } from "../src/state/appearance";

function render(element: ReactElement): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

afterEach(() => {
  appearanceStore.reset();
});

describe("AppearanceControls — bound to the pin, not a second inspector", () => {
  it("emits one toolbar of exactly the four toggles", () => {
    const host = render(<AppearanceControls />);
    const cluster = host.querySelector("[data-appearance]");
    expect(cluster?.getAttribute("role")).toBe("toolbar");
    for (const field of APPEARANCE_TOGGLES) {
      expect(host.querySelector(`[data-appearance-control="${field}"]`)).not.toBeNull();
    }
    const order = [...host.querySelectorAll("[data-appearance-control]")].map((node) =>
      node.getAttribute("data-appearance-control"),
    );
    // Every member is an `appearanceStore` FLAG, in draw order. `triad` left
    // with the axis triad itself and `fit` left later the same day (2026-09-20)
    // — a toggle whose flag nothing reads is a control that lies about having
    // an effect, and Fit was the one member that was not a flag at all.
    expect(order).toEqual(["grid", "wireframe", "ortho", "materialOverride"]);
    expect(host.querySelector('[data-appearance-control="triad"]')).toBeNull();
    expect(host.querySelector('[data-appearance-control="fit"]')).toBeNull();
  });

  it("draws every toggle — no disclosure to open (2026-09-20)", () => {
    // Three of these sat behind a "Show view options" chevron, from when they
    // were WORDS and a row could not hold five. As icons in a 36px column they
    // cost 30px each, so the chevron was a click to save 90px of the narrowest
    // thing on screen, plus a second state to remember.
    const host = render(<AppearanceControls />);
    expect(host.querySelector("[data-appearance-more]")).toBeNull();
    expect(host.querySelector("[data-appearance-extras]")).toBeNull();
    for (const field of APPEARANCE_TOGGLES) {
      const control = host.querySelector(`[data-appearance-control="${field}"]`);
      expect(control, field).not.toBeNull();
      expect(control?.hasAttribute("hidden"), field).toBe(false);
    }
  });

  it("defaults match the authored picture — G4.5/§3.11.2 must not move by existing", () => {
    const host = render(<AppearanceControls />);
    const pressed = (field: string): string | null =>
      host.querySelector(`[data-appearance-control="${field}"]`)?.getAttribute("aria-pressed") ??
      null;
    expect(pressed("wireframe")).toBe("false");
    // Perspective by default since 2026-09-20; see `state/appearance.ts`.
    expect(pressed("ortho")).toBe("false");
    expect(pressed("grid")).toBe("true");
    expect(pressed("materialOverride")).toBe("true");
  });

  it("draws no Fit control, and takes no props to drive one (2026-09-20)", () => {
    // LOST COVERAGE, recorded rather than deleted. Two cases lived here: Fit
    // disabled with a reason when no pinned GLB was on the canvas, and enabled
    // when there was one. Both are gone because the control is gone, and with
    // it `state/viewportFit.ts` — the module store that carried its handler
    // from the viewport to its sibling rail.
    //
    // The CAPABILITY is not wholly gone: `Viewport.tsx` calls `engine.frame()`
    // whenever the framing key (named view + explode state) changes, so every
    // view-cube click still re-frames. What no longer has a UI path is
    // re-framing when that key is UNCHANGED — after a free orbit, which settles
    // the camera onto the nearest view name without refitting zoom or pan. The
    // recovery there is to click any cube face but the current one.
    const host = render(<AppearanceControls />);
    expect(host.querySelector('[data-appearance-control="fit"]')).toBeNull();
    expect([...host.querySelectorAll("[data-icon]")].map((n) => n.getAttribute("data-icon"))).not.toContain(
      "fit",
    );
  });

  it("draws only ids already in the closed set — §3.12 stays closed", () => {
    // The cluster moved into the 44px stage rail (2026-09-20), so View is now a
    // chevron rather than the phrase "Show view options". That is allowed and
    // this assertion still holds the line that matters: the id must ALREADY be
    // in §3.12's vocabulary. Adding one is a spec edit, and "draws no icon at
    // all" was a stricter rule than the section states.
    const host = render(<AppearanceControls />);
    const drawn = [...host.querySelectorAll("[data-icon]")].map((node) =>
      node.getAttribute("data-icon"),
    );
    expect(drawn.length).toBeGreaterThan(0);
    for (const id of drawn) {
      expect(ICON_IDS, `${String(id)} must be in the closed set`).toContain(id);
    }
    // And every name survives its word becoming a glyph.
    for (const control of host.querySelectorAll("[data-appearance-control]")) {
      expect(control.getAttribute("aria-label")).toBeTruthy();
      expect(control.textContent).toBe("");
    }
  });
});
