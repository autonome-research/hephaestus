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
  it("emits one toolbar with the five toggles and Fit", () => {
    const host = render(<AppearanceControls canFit onFit={() => undefined} />);
    const cluster = host.querySelector("[data-appearance]");
    expect(cluster?.getAttribute("role")).toBe("toolbar");
    for (const field of APPEARANCE_TOGGLES) {
      expect(host.querySelector(`[data-appearance-control="${field}"]`)).not.toBeNull();
    }
    expect(host.querySelector('[data-appearance-control="fit"]')).not.toBeNull();
    const order = [...host.querySelectorAll("[data-appearance-control]")].map((node) =>
      node.getAttribute("data-appearance-control"),
    );
    expect(order).toEqual(["wireframe", "fit", "ortho", "grid", "triad", "materialOverride"]);
  });

  it("defaults match the authored picture — G4.5/§3.11.2 must not move by existing", () => {
    const host = render(<AppearanceControls canFit onFit={() => undefined} />);
    const pressed = (field: string): string | null =>
      host.querySelector(`[data-appearance-control="${field}"]`)?.getAttribute("aria-pressed") ??
      null;
    expect(pressed("wireframe")).toBe("false");
    expect(pressed("ortho")).toBe("true");
    expect(pressed("grid")).toBe("true");
    expect(pressed("triad")).toBe("true");
    expect(pressed("materialOverride")).toBe("true");
  });

  it("disables Fit when no pinned artifact is on the canvas, with a reason", () => {
    const host = render(<AppearanceControls canFit={false} onFit={() => undefined} />);
    const fit = host.querySelector('[data-appearance-control="fit"]');
    expect(fit?.getAttribute("aria-disabled")).toBe("true");
    expect(fit?.getAttribute("title")).toBeTruthy();
    expect(fit?.getAttribute("aria-describedby")).toBeTruthy();
  });

  it("keeps Fit enabled when the pin is on the canvas", () => {
    const host = render(<AppearanceControls canFit onFit={() => undefined} />);
    const fit = host.querySelector('[data-appearance-control="fit"]');
    expect(fit?.getAttribute("aria-disabled")).not.toBe("true");
  });

  it("does not introduce an icon id — §3.12 stays closed", () => {
    const host = render(<AppearanceControls canFit onFit={() => undefined} />);
    expect(host.querySelector("[data-icon]")).toBeNull();
  });
});
