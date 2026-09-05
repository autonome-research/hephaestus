// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The view cube's hit model (INTERFACE.md §5.5; `docs/audit-2026-09-04-broken.md`
// B-7).
//
// ONE COMPUTATION FOR THE PICTURE AND THE HIT MAP. The shipped cube was a CSS
// `preserve-3d` stack: six 56×56 faces, four 14×56 slabs driven *through* the
// body's middle, and five 16×16 plates at a 20px margin. Those are not a cube's
// edges and corners — they are plates through its interior — so hit testing
// resolved by paint order inside one stacking context, and `Front / Top`
// collected 516px over `Top`'s 739. On top of that the parent transform was
// `rotateZ(-azimuth)`, a roll in the SCREEN plane, so the cube never turned on
// its vertical axis: `Front` faced the viewer at every azimuth and `Back` was
// culled by `backface-visibility` at every azimuth. Ten of fifteen targets were
// reachable at `iso`; six of fifteen at each axis view, and the reachable SET
// was identical across azimuth 0, 90, 180 and 270.
//
// This module replaces both mechanisms with one orthographic projection. The
// drawn cell and the hit region are the same polygon by construction, so
// "reachable" is not a property that can drift away from "drawn".
//
// THE SOLID IS A BEVELLED CUBE, and the bevel is what makes the inventory
// closed and the tiling exact. Take the cube |x|,|y|,|z| ≤ 1 and cut every edge
// and every corner back to `INSET`. The surface is then exactly 6 face squares,
// 12 edge quads and 8 corner triangles — twenty-six cells, one per direction in
// {-1,0,1}³ minus the origin, each planar and convex, each with its own
// direction as its outward normal. Because the solid is CONVEX, the cells whose
// normal faces the eye project to a tiling of the silhouette with no overlap
// and no gap: non-overlap is a theorem here, not a tuned constant, which is the
// whole point of retiring the `preserve-3d` stack.
//
// THE VOCABULARY HAS ONE IMPLEMENTATION. `targetName` delegates to
// `nameForDirection` in `./cameras.ts` — the same function free orbit already
// snapshots through — so every cell's `view` is a camera `heph render` can
// reproduce (§5.5) and the `+++` corner comes back as `iso` for free. The cube
// does not carry a second table of angles; the hand-written one it used to
// carry is exactly how the button labelled "Right / Top" came to write
// `az0_el35`, a camera above the `+X` FACE.
//
// Nothing here touches the DOM. `ViewCube.tsx` renders what this module
// computes and `web/test/cubeTargets.test.ts` checks it without a browser.

import {
  eyeDirection,
  nameForDirection,
  upHint,
  type ViewAngles,
} from "./cameras";

/** The scene box, in px. `ViewCube.module.css` declares the same number. */
export const CUBE_SIZE = 72;

/**
 * The cube's half-extent in px.
 *
 * Sized so the projected solid fits the scene box at EVERY camera: the widest
 * silhouette (a corner view) reaches 33.1px from the centre, inside the 36px
 * half-box, and the tightest visible cell is still 52px² with a 5.5px minimum
 * bounding-box side — a real click target rather than a hairline.
 */
const SCALE = 27;

/**
 * How much of a half-edge a face cell keeps; the rest is bevel.
 *
 * At 0.5 a face cell is half the face's width and the edge and corner cells
 * that surround it are a quarter of it each — the proportions of a Smith-style
 * cube, and the value that maximises the smallest hit region.
 */
const INSET = 0.5;

/** Facing-the-eye test. Above float noise, below any real cell (§5.5). */
const FACING = 1e-6;

export type CubeKind = "face" | "edge" | "corner";

type Vec3 = readonly [number, number, number];
type Vec2 = readonly [number, number];

/** One of the twenty-six selectable cells of the bevelled cube. */
export interface CubeTarget {
  /** The `{-1,0,1}³` triple, as a string — a stable React key and a test handle. */
  readonly key: string;
  /** That triple itself: the cell's position on the cube, before normalising. */
  readonly axis: Vec3;
  /** The cell's outward normal, unit length — the camera it selects. */
  readonly direction: Vec3;
  /** Derived from the count of non-zero components; never hand-assigned. */
  readonly kind: CubeKind;
  /** `targetName(direction)`: the `view` a click writes into workspace state. */
  readonly view: string;
}

/** A `CubeTarget` placed on the screen for one camera. */
export interface ProjectedTarget extends CubeTarget {
  /** `direction · eye`. Positive means the cell faces the viewer. */
  readonly depth: number;
  /** False when the cell faces away; such a cell is neither drawn nor hittable. */
  readonly visible: boolean;
  /** The cell's centroid, px, origin at the scene centre, `y` DOWN as in CSS. */
  readonly x: number;
  readonly y: number;
  /** The cell's projected outline, same frame as `x`/`y`, wound anticlockwise. */
  readonly polygon: readonly Vec2[];
  /**
   * The button's box, px from the scene box's top-left. It is CENTRED ON THE
   * CELL'S CENTROID rather than being the polygon's tight bounding box: a
   * centroid lies strictly inside a convex polygon, so the point a click lands
   * on by default is inside the clip region for a triangle as well as a quad.
   */
  readonly box: { readonly left: number; readonly top: number; readonly width: number; readonly height: number };
  /** `polygon` expressed inside `box`, ready for `clip-path: polygon(...)`. */
  readonly clip: readonly Vec2[];
  /**
   * The 2D affine that maps the face's own square — local `[-SCALE, SCALE]²`,
   * `y` down, upright at that face's own standard view — onto its projection.
   * A face word laid out in that frame is painted ONTO the cube instead of
   * floating over it, and the map never magnifies, so the word is drawn at its
   * declared type size or smaller. `null` for edges and corners, which carry an
   * accessible name and no drawn word.
   */
  readonly frame: readonly [number, number, number, number, number, number] | null;
}

function cross(a: Vec3, b: Vec3): Vec3 {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}

function dot(a: Vec3, b: Vec3): number {
  return a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
}

function unit(a: Vec3): Vec3 {
  const length = Math.hypot(a[0], a[1], a[2]);
  return length === 0 ? [0, 0, 0] : [a[0] / length, a[1] / length, a[2] / length];
}

/**
 * The screen basis for a camera looking from `direction`, built exactly as
 * `cameras.ts` defines one: `upHint` decides the pole case, right is
 * `up × eye`, and up is `eye × right`. Used for the VIEW and, unchanged, for
 * each face's own text frame — "the face's word sits the way that face's own
 * camera would show it" is then one rule rather than a table of six.
 */
function screenBasis(direction: Vec3): { readonly right: Vec3; readonly up: Vec3 } {
  const right = unit(cross(upHint(direction), direction));
  return { right, up: cross(direction, right) };
}

/** World vector → px, `y` DOWN (CSS), origin at the scene centre. */
function toScreen(point: Vec3, basis: { readonly right: Vec3; readonly up: Vec3 }): Vec2 {
  return [SCALE * dot(point, basis.right), -SCALE * dot(point, basis.up)];
}

function kindOf(axis: Vec3): CubeKind {
  const filled = axis.filter((component) => component !== 0).length;
  return filled === 1 ? "face" : filled === 2 ? "edge" : "corner";
}

/**
 * The bevelled cube's cell for one direction, in cube space.
 *
 * ONE RULE FOR ALL THREE KINDS: a vertex takes its FULL value on exactly one
 * of the direction's non-zero axes, the inset value on the others, and ±INSET
 * on each axis the direction leaves at zero. That is 4 vertices for a face,
 * 4 for an edge and 3 for a corner — the bevelled cube's own faces.
 */
function cellVertices(axis: Vec3): readonly Vec3[] {
  const filled: number[] = [];
  const free: number[] = [];
  for (let i = 0; i < 3; i += 1) ((axis[i] ?? 0) === 0 ? free : filled).push(i);

  const vertices: Vec3[] = [];
  for (const full of filled) {
    for (let mask = 0; mask < 1 << free.length; mask += 1) {
      const point: [number, number, number] = [0, 0, 0];
      for (const i of filled) {
        const value = axis[i] ?? 0;
        point[i] = i === full ? value : value * INSET;
      }
      free.forEach((i, bit) => {
        point[i] = (mask & (1 << bit)) === 0 ? -INSET : INSET;
      });
      vertices.push(point);
    }
  }

  // Wind them around the cell's own normal, so the polygon is a simple outline
  // in every projection rather than a bow-tie in some of them.
  const direction = unit(axis);
  const basis = screenBasis(direction);
  return [...vertices].sort(
    (a, b) =>
      Math.atan2(dot(a, basis.up), dot(a, basis.right)) -
      Math.atan2(dot(b, basis.up), dot(b, basis.right)),
  );
}

function buildTargets(): readonly CubeTarget[] {
  const targets: CubeTarget[] = [];
  for (const x of [-1, 0, 1]) {
    for (const y of [-1, 0, 1]) {
      for (const z of [-1, 0, 1]) {
        if (x === 0 && y === 0 && z === 0) continue;
        const axis: Vec3 = [x, y, z];
        const direction = unit(axis);
        targets.push({
          key: `${String(x)},${String(y)},${String(z)}`,
          axis,
          direction,
          kind: kindOf(axis),
          view: targetName(direction),
        });
      }
    }
  }
  return targets;
}

/**
 * The camera a cell selects, in the server's own vocabulary.
 *
 * `nameForDirection` is `cameras.ts`'s snapshot rule and the only naming
 * implementation in the client; this function adds exactly one substitution and
 * states why. `cameras.py` gives `-Y` and `front` THE SAME ANGLES, so they are
 * one camera with two names, and `nameForDirection` returns the first in
 * `STANDARD_VIEWS` order — `-Y`. The cube draws that face with the word
 * "Front" and §5.5 C19 addresses it as `data-view="front"`, so the cube spells
 * this one camera with its other, equally valid name. Both still resolve to the
 * same camera on the way back in, so no URL changes meaning.
 */
export function targetName(direction: Vec3): string {
  const name = nameForDirection(direction);
  return name === "-Y" ? "front" : name;
}

/**
 * All twenty-six cells, and the set is CLOSED: six faces, twelve edges, eight
 * corners. The shipped cube carried six faces, four of twelve edges and five of
 * eight corners, which is why §5.5's "faces, edges, and corners are selectable"
 * needs the inventory written down beside it.
 */
export const CUBE_TARGETS: readonly CubeTarget[] = buildTargets();

/**
 * Place every target for one camera.
 *
 * The angles are the server's own `ViewSpec` pair, so a caller passes
 * `viewAngles(view)` straight through and the cube is drawn for the camera the
 * URL names. Every target is returned — a caller that renders only `visible`
 * ones gets §5.5's negative half (a cell that is not drawn is not hittable) for
 * free, and a test can still see what was culled and why.
 */
export function projectTargets(azimuthDeg: number, elevationDeg: number): readonly ProjectedTarget[] {
  const angles: ViewAngles = { azimuth_deg: azimuthDeg, elevation_deg: elevationDeg };
  const eye = eyeDirection(angles);
  const view = screenBasis(eye);
  const half = CUBE_SIZE / 2;

  return CUBE_TARGETS.map((target): ProjectedTarget => {
    const depth = dot(target.direction, eye);
    const polygon = cellVertices(target.axis).map((vertex) => toScreen(vertex, view));

    // The centroid, and a box centred on it (see `box` above for why centred
    // rather than tight).
    let cx = 0;
    let cy = 0;
    for (const point of polygon) {
      cx += point[0] / polygon.length;
      cy += point[1] / polygon.length;
    }
    let halfWidth = 0;
    let halfHeight = 0;
    for (const point of polygon) {
      halfWidth = Math.max(halfWidth, Math.abs(point[0] - cx));
      halfHeight = Math.max(halfHeight, Math.abs(point[1] - cy));
    }
    const left = half + cx - halfWidth;
    const top = half + cy - halfHeight;

    return {
      ...target,
      depth,
      visible: depth > FACING,
      x: cx,
      y: cy,
      polygon,
      box: { left, top, width: halfWidth * 2, height: halfHeight * 2 },
      clip: polygon.map((point): Vec2 => [half + point[0] - left, half + point[1] - top]),
      frame: target.kind === "face" ? faceFrame(target.direction, view) : null,
    };
  });
}

/**
 * The face's own square, mapped onto its projection (see `frame` above).
 *
 * Local `(lx, ly)` with `ly` DOWN maps to `centre + (lx/SCALE)·right −
 * (ly/SCALE)·up`, where `right` and `up` are the face's own screen basis
 * projected through the view's. In CSS/SVG matrix order that is
 * `(a b c d e f)` with `a = right.x/SCALE` and so on.
 */
function faceFrame(
  direction: Vec3,
  view: { readonly right: Vec3; readonly up: Vec3 },
): readonly [number, number, number, number, number, number] {
  const face = screenBasis(direction);
  const right = toScreen(face.right, view);
  const up = toScreen(face.up, view);
  const centre = toScreen(direction, view);
  return [
    right[0] / SCALE,
    right[1] / SCALE,
    -up[0] / SCALE,
    -up[1] / SCALE,
    centre[0],
    centre[1],
  ];
}
