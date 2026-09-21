// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The stage rail's gate on the appearance cluster (§4.1, §5.3 C19).
//
// This file exists because of a defect the unit suite could not have caught
// and the e2e suite had not been run to catch: when Fit was struck, the
// cluster's gate moved off `state/viewportFit.ts` (the store the viewport
// published a handler to) and onto the stage tab. That is correct for
// PRESENCE — `Stage` mounts `Viewport` if and only if the tab is `viewport` —
// but it silently dropped C19's second condition, which the store had never
// carried either: behind a rendered section plate the four canvas-authoring
// overlays unmount, because they drive a camera the reader is not looking at.
//
// `viewport.spec.ts` asserts `[data-appearance]` has count 0 over a plate. The
// predicate now lives in `viewport/section.ts` and both callers use it, so the
// assertions below are about the SHARED answer rather than either component's
// copy of it.

import { describe, expect, it } from "vitest";
import { plateOwnsWell } from "../src/viewport/section";

describe("plateOwnsWell — one predicate, two subtrees", () => {
  it("is true only for a section overlay with a parseable plane", () => {
    expect(plateOwnsWell("section", "+X@0")).toBe(true);
    expect(plateOwnsWell("section", "-Z@12.5")).toBe(true);
  });

  it("is false without the section overlay, whatever the plane says", () => {
    expect(plateOwnsWell(null, "+X@0")).toBe(false);
    expect(plateOwnsWell("dfm", "+X@0")).toBe(false);
  });

  it("is false with the overlay but no plane to render", () => {
    expect(plateOwnsWell("section", null)).toBe(false);
  });

  it("is false for a plane spelling the parser rejects", () => {
    // A hand-edited URL must draw the cluster, not hide it: an unparseable
    // plane renders no plate, so nothing is covering the canvas.
    expect(plateOwnsWell("section", "sideways")).toBe(false);
    expect(plateOwnsWell("section", "+W@0")).toBe(false);
    expect(plateOwnsWell("section", "+X@")).toBe(false);
  });
});
