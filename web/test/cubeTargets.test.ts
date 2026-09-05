// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// B-7 — the projected 2D hit model (INTERFACE.md §5.5, audit-2026-09-04 B-7).
//
// The fix design (`docs/audit-2026-09-04-broken.md` B-7 "Fix", step 1) puts the
// cube's whole vocabulary in ONE pure, DOM-free module: `CUBE_TARGETS` is all
// 26 directions in `{-1,0,1}^3` minus the origin, `targetName` delegates to
// `nameForDirection` (`viewport/cameras.ts`) so the naming rule has one
// implementation, and `projectTargets` builds the camera basis exactly as
// `cameras.ts` defines it and returns each target's screen position and depth,
// culling anything facing away from the eye.
//
// THIS FILE IS RED UNTIL `web/src/viewport/cubeTargets.ts` EXISTS. That module
// is a source file this lane's test-author role does not create — see the
// round's handoff notes for the exact shape a later round is expected to land.

import { describe, expect, it } from "vitest";
import {
  CUBE_TARGETS,
  projectTargets,
  targetName,
  type CubeTarget,
} from "../src/viewport/cubeTargets";
import { STANDARD_VIEWS } from "../src/state/workspace";
import { ISO_ELEVATION_DEG, anglesFromDirection, eyeDirection, viewAngles } from "../src/viewport/cameras";

/** Angle between two unit vectors, in degrees. */
function angleBetween(a: readonly [number, number, number], b: readonly [number, number, number]): number {
  const dot = a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  return (Math.acos(Math.min(1, Math.max(-1, dot))) * 180) / Math.PI;
}

describe("CUBE_TARGETS — the closed inventory (B-7 fix step 1)", () => {
  it("is exactly 26 targets: six faces, twelve edges, eight corners", () => {
    expect(CUBE_TARGETS).toHaveLength(26);
    const byKind = { face: 0, edge: 0, corner: 0 } as Record<CubeTarget["kind"], number>;
    for (const target of CUBE_TARGETS) byKind[target.kind] += 1;
    expect(byKind.face).toBe(6);
    expect(byKind.edge).toBe(12);
    expect(byKind.corner).toBe(8);
  });

  it("kinds are derived from the count of non-zero direction components", () => {
    for (const target of CUBE_TARGETS) {
      const nonZero = target.direction.filter((component) => component !== 0).length;
      const expected = nonZero === 1 ? "face" : nonZero === 2 ? "edge" : "corner";
      expect(target.kind, JSON.stringify(target.direction)).toBe(expected);
    }
  });

  it("every direction is a unit vector", () => {
    for (const target of CUBE_TARGETS) {
      const length = Math.hypot(...target.direction);
      expect(length, JSON.stringify(target.direction)).toBeCloseTo(1, 6);
    }
  });
});

describe("targetName — one naming implementation, delegated to cameras.ts (B-7)", () => {
  it("round-trips every target's name through the camera module's angle parser to within 1°", () => {
    for (const target of CUBE_TARGETS) {
      const name = targetName(target.direction);
      const angles = viewAngles(name);
      expect(angles, `${name} does not parse as a view`).not.toBeNull();
      const reconstructed = eyeDirection(angles!);
      const drift = angleBetween(target.direction, reconstructed);
      expect(drift, `${name} drifted ${String(drift)}° from ${JSON.stringify(target.direction)}`).toBeLessThanOrEqual(1);
    }
  });

  it("the +++ corner is exactly iso", () => {
    const iso = CUBE_TARGETS.find(
      (target) => target.direction[0] > 0 && target.direction[1] > 0 && target.direction[2] > 0,
    );
    expect(iso, "no +++ corner in the inventory").toBeDefined();
    expect(targetName(iso!.direction)).toBe("iso");
  });

  it("the -Y face is exactly front", () => {
    const negY = CUBE_TARGETS.find(
      (target) => target.kind === "face" && target.direction[0] === 0 && target.direction[1] < 0 && target.direction[2] === 0,
    );
    expect(negY, "no -Y face in the inventory").toBeDefined();
    expect(targetName(negY!.direction)).toBe("front");
  });

  it("no two targets share a name", () => {
    const names = CUBE_TARGETS.map((target) => targetName(target.direction));
    expect(new Set(names).size).toBe(names.length);
  });

  // AMENDED by the implementing round: the original assertion here asked for
  // all EIGHT `STANDARD_VIEWS` names in the inventory, and that is unsatisfiable
  // against the two assertions above it. `cameras.py` gives `-Y` and `front`
  // THE SAME ANGLES (270°, 0°) — one camera with two names, which `cameras.ts`
  // states in as many words — so the `-Y` face is ONE cell, it can carry only
  // one name, and B-7's fix design names it `front` ("the `-Y` face must be
  // given the literal name `front`"). A 26-target inventory whose names are
  // unique therefore spells that camera exactly once. What the inventory owes
  // §5.5 is every distinct CAMERA, not every spelling of one, so that is what
  // is asserted.
  it("names every standard CAMERA in the inventory (`-Y` and `front` being one)", () => {
    const names = new Set(CUBE_TARGETS.map((target) => targetName(target.direction)));
    for (const standard of STANDARD_VIEWS) {
      if (standard === "-Y") {
        expect(names.has("front"), "the -Y camera, spelled front").toBe(true);
        continue;
      }
      expect(names.has(standard), standard).toBe(true);
    }
  });
});

describe("projectTargets — visibility and depth (B-7 fix step 1)", () => {
  it("shows exactly one face at each of the six standard axis views", () => {
    for (const view of STANDARD_VIEWS) {
      if (view === "iso") continue;
      const angles = viewAngles(view)!;
      const eye = eyeDirection(angles);
      const projected = projectTargets(angles.azimuth_deg, angles.elevation_deg);
      const visibleFaces = projected.filter((target) => target.visible && target.kind === "face");
      expect(visibleFaces, view).toHaveLength(1);
      // `-Y` and `front` name the same camera (cameras.ts's documented pair), so
      // the assertion is on the DIRECTION the visible face carries, never on a
      // name string that could be either of two correct spellings.
      expect(angleBetween(visibleFaces[0]!.direction, eye), view).toBeLessThan(1);
    }
  });

  it("shows exactly three faces at iso", () => {
    const angles = { azimuth_deg: 45, elevation_deg: ISO_ELEVATION_DEG };
    const projected = projectTargets(angles.azimuth_deg, angles.elevation_deg);
    const visibleFaces = projected.filter((target) => target.visible && target.kind === "face");
    expect(visibleFaces).toHaveLength(3);
  });

  it("the target whose direction equals the eye direction has maximum depth", () => {
    for (const view of STANDARD_VIEWS) {
      const angles = viewAngles(view)!;
      const eye = eyeDirection(angles);
      const projected = projectTargets(angles.azimuth_deg, angles.elevation_deg);
      const maxDepth = Math.max(...projected.map((target) => target.depth));
      const winners = projected.filter((target) => target.depth === maxDepth);
      // Every winner's direction must equal the eye direction (within float slop);
      // at a standard view exactly one target's direction IS the eye direction.
      for (const winner of winners) {
        expect(angleBetween(winner.direction, eye), `${view}: ${JSON.stringify(winner.direction)}`).toBeLessThan(1);
      }
    }
  });

  it("culls a target facing away from the eye", () => {
    const angles = viewAngles("+X")!;
    const projected = projectTargets(angles.azimuth_deg, angles.elevation_deg);
    const negX = projected.find(
      (target) => target.direction[0] < 0 && target.direction[1] === 0 && target.direction[2] === 0,
    );
    expect(negX, "no -X face in the projection").toBeDefined();
    expect(negX!.visible).toBe(false);
  });

  it("every direction reconstructed by anglesFromDirection agrees with the target's own direction", () => {
    // Sanity: the projection module and the camera module agree on the same
    // sphere, so a target's angles round-trip through BOTH directions.
    for (const target of CUBE_TARGETS) {
      const angles = anglesFromDirection(target.direction);
      const back = eyeDirection(angles);
      expect(angleBetween(target.direction, back)).toBeLessThan(0.01);
    }
  });
});
