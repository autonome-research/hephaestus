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
/**
 * The gizmo's frame, in px. 120 since 2026-09-20.
 *
 * It was 72 — the cube's own bounding box with almost nothing round it — and
 * the axes now reach PAST the cube, so at 72 their arms and letters were
 * clipped away by `.scene`'s `overflow: hidden` and the gizmo looked like a
 * bare block. The cube itself is unchanged: `SCALE` still sizes it, and this
 * only buys the room the arms need.
 */
export const CUBE_SIZE = 120;

/**
 * The cube's half-extent in px.
 *
 * Sized so the projected solid fits the scene box at EVERY camera: the widest
 * silhouette (a corner view) reaches 33.1px from the centre, inside the 36px
 * half-box.
 *
 * THE CELL-SIZE HALF OF THIS NOTE IS STALE and is restated rather than left to
 * be read as current: it was written at `SCALE = 27` with a half-face bevel,
 * where the tightest visible cell measured 52px² with a 5.5px minimum side. At
 * 20 with the fine chamfer below, the tightest is about 7x3px. That is the
 * trade this pair of numbers makes — the arms need the room and a fine chamfer
 * is what makes the block read as a cube — and 3px is the floor
 * `test/cubeTargets.tsx` holds it to.
 */
const SCALE = 20;
// 20, not 27 (2026-09-20). The gizmo is a CUBE PLUS THREE AXES, and the axes
// are the half that says which way the model is turned — a cube filling the
// frame left them as short stubs poking out of it. Shrinking the block is
// what lengthens the arms without growing the widget.

/**
 * How much of a half-edge a face cell keeps; the rest is bevel.
 *
 * 0.7 (restored 2026-09-20): seven tenths of the face, and the rest split
 * between the two bevels that border it. §5.2 closes the inventory at
 * twenty-six, and this number is what gives twenty of them any area at all —
 * at 1 the edge and corner cells collapse to nothing, which is a way of
 * deleting them that leaves the array the right length and every assertion
 * about it passing.
 *
 * It WAS set to 1 for a reason and the reason is answered rather than
 * dismissed. The complaint was that the three visible faces stood apart as
 * separate plates instead of meeting at the cube's own edges, and half of that
 * was the FILL: the bevel cells were painted `--surface-raised`, a panel
 * colour, so the chamfer read as chrome showing through.
 * `ViewCube.module.css` shades them from the cube's own palette now. The other
 * half was this number — at 0.5 the bevel is as wide as the face it borders
 * and the solid reads as a faceted ball rather than a block, which is the
 * reference's shape and not ours.
 *
 * 0.7 is where the two meet, and the number is bounded on both sides rather
 * than picked: drawn, it is a cube with a fine chamfer; hit, its tightest
 * corner at iso measures 3.27px on its short side, over the 3px floor
 * `test/cubeTargets.tsx` holds every drawn cell to. 0.75 measures 2.72 and
 * fails that floor; 0.5 passes it easily and draws a faceted ball.
 */
const INSET = 0.7;

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
  let right = toScreen(face.right, view);
  let up = toScreen(face.up, view);
  const centre = toScreen(direction, view);

  // NEVER UPSIDE DOWN (2026-09-20). Each face's word is laid out in that
  // face's OWN camera basis, which is the rule that makes "the word sits the
  // way that face's camera would show it" one line instead of a table of six.
  // It has one consequence the rule does not mention: from a camera above the
  // model, the top face's own up-vector projects DOWNWARD on screen, and the
  // word is drawn inverted — "Top" rendered as "doʇ".
  //
  // A word the reader has to tilt their head for is not a label. Where the
  // frame would flip, both basis vectors are negated: that is a 180° turn of
  // the same frame, so the word stays ON the face and in its plane, and only
  // its reading direction changes.
  if (up[1] > 0) {
    right = [-right[0], -right[1]];
    up = [-up[0], -up[1]];
  }

  return [
    right[0] / SCALE,
    right[1] / SCALE,
    -up[0] / SCALE,
    -up[1] / SCALE,
    centre[0],
    centre[1],
  ];
}

/** One world axis, projected for the same camera the cube is drawn for. */
export interface ProjectedAxis {
  /** `X`, `Y` or `Z` — the letter drawn at the tip. */
  readonly label: "X" | "Y" | "Z";
  /** Tip position in screen px, `y` DOWN, origin at the scene centre. */
  readonly tip: Vec2;
  /** Where the letter sits — a little beyond the tip, so it clears the line. */
  readonly text: Vec2;
  /** Component along the view direction; negative is toward the viewer. */
  readonly depth: number;
}

/**
 * The three world axes for one camera.
 *
 * THE SAME BASIS THE CUBE USES, deliberately. An axis indicator drawn from its
 * own projection is a second answer to "which way is +X", and the two drift the
 * moment one of them is touched; sharing `screenBasis` makes agreement
 * structural rather than something a test has to check.
 *
 * Monochrome, like the triad this replaces: §3.11.6's rule is that the viewport
 * never spends a status colour on decoration, because red in this app means
 * `fail`. Direction is carried by the LETTER and the line, which is what a
 * reader needs from an axis indicator anyway.
 */
export function projectAxes(
  azimuthDeg: number,
  elevationDeg: number,
  reach = 1,
): readonly ProjectedAxis[] {
  const eye = eyeDirection({ azimuth_deg: azimuthDeg, elevation_deg: elevationDeg });
  const basis = screenBasis(eye);
  const axes: readonly { readonly label: "X" | "Y" | "Z"; readonly vector: Vec3 }[] = [
    { label: "X", vector: [1, 0, 0] },
    { label: "Y", vector: [0, 1, 0] },
    { label: "Z", vector: [0, 0, 1] },
  ];

  return axes.map(({ label, vector }): ProjectedAxis => {
    const scaled: Vec3 = [vector[0] * reach, vector[1] * reach, vector[2] * reach];
    const tip = toScreen(scaled, basis);
    // The letter sits just beyond the tip. 1.12 rather than 1.28 since
    // 2026-09-20: the arms are long enough now that the old overshoot pushed
    // the letters outside the frame, where `.scene` clips them.
    const over: Vec3 = [vector[0] * reach * 1.12, vector[1] * reach * 1.12, vector[2] * reach * 1.12];
    return { label, tip, text: toScreen(over, basis), depth: dot(vector, eye) };
  });
}
