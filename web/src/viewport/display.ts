// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Viewport display authorship (INTERFACE.md §3.11, plan item 6).
//
// §3.11 is the one complaint no CSS could answer: the geometry the tool exists
// to show was the dimmest object on screen. This module is the client's display
// opinion — the material, the edges, the ground grid and the palette they are
// all drawn from. `engine.ts` owns the GPU; this file owns what the GPU is told
// to draw, and holds no WebGL of its own so it is exercisable in vitest exactly
// as `scene.ts` is.
//
// ═══ WHY THE PART WAS BLACK, AND WHY THE SPEC'S DIAGNOSIS IS HALF RIGHT ══════
//
// §3.11 attributes the flat desaturated grey to a missing `outputColorSpace`.
// **Measured against three@0.185.1, that half of the diagnosis no longer holds:**
// `WebGLRenderer` has defaulted `outputColorSpace` to `SRGBColorSpace` since
// r152 (`three.module.js`:16298 — `this._outputColorSpace = SRGBColorSpace`), so
// the shipped build was *already* writing sRGB. `toneMapping` really does
// default to `NoToneMapping` (`:16263`), so that half stands and is set below.
//
// The actual cause is the one the 2026-08-28 review named when it refused a
// wholesale material override, and it is worth writing down because it is also
// the reason the override must be careful rather than absent:
//
//   `core/render/gltf.py`:206-215 sets each solid's
//   `baseColorFactor = id_to_rgb(solid_id) / 255`, and `id_to_rgb` encodes the
//   id as the 24-bit big-endian integer `id + 1` (`palette.py`:60-69). Solid 0
//   is therefore `(0, 0, 1)/255` — **albedo zero to three decimal places**. The
//   sampled `rgb(25,25,34)` was never a colour-space artefact; it was a black
//   part lit by white lights. The GLB's `baseColorFactor` is not a display
//   colour that happens to be dark. It is a *selection ID wearing a colour's
//   clothes*, and no lighting rig or tone curve can rescue it.
//
// ═══ HOW THE ID CHANNEL SURVIVES THE OVERRIDE ═══════════════════════════════
//
// The review refuted "override materials wholesale" precisely because that
// channel is real. Three things keep it intact, and none of them is a promise:
//
// 1. **The GLB bytes are never touched.** `useGlb` holds the artifact's bytes
//    and `engine.load` parses them; authorship happens on the *scene graph* the
//    loader built, downstream of the document. The artifact a later request
//    re-fetches, and the artifact `resolve_gltf_pick` reads server-side, is
//    byte-identical to the one the server published.
// 2. **The exporter's material is preserved on the node, not discarded.** Every
//    overridden mesh keeps its loader-built material at
//    `userData[SOURCE_MATERIAL_KEY]`, un-mutated and **never disposed**. The
//    `baseColorFactor` triple is still readable off the live scene graph after
//    authorship, which `test/viewport.test.ts` asserts by reconstructing the
//    exporter's 0-255 values from it.
// 3. **The authoritative channel was never the colour anyway.** `gltf.py` puts
//    `selection_id` in mesh **and** primitive `extras`, and
//    `resolve_gltf_pick` resolves a pick through those extras and the linked
//    bundle — not through a pixel and not through a material. The colour is a
//    parallel encoding that only the *mask passes* are ever decoded from, and
//    §5.4 is explicit that a mask is never decoded from the viewport, "which is
//    lit and antialiased". Authoring the material changes nothing a mask pass
//    is read from, because a mask pass is server pixels.
//
// **The one thing this module must therefore never do is expose the preserved
// colour to anything the app renders.** `glb.ts` refuses to parse
// `selection_id` on the grounds that "a client that had the ID in hand would
// eventually submit it"; a client that could read `id_to_rgb(solid_id)` back off
// a material would have the ID by arithmetic. So the preserved material is
// reachable only from this module's own key, no exported function returns it,
// and `testHook.ts` does not publish it.
//
// ═══ WHAT IS AUTHORED, CLAUSE BY CLAUSE (§3.11's normative list) ═════════════
//
//   1. ground        `engine.ts`, from `--viewport-ground` (landed with item 3)
//   2. material      `authorDisplay` below, at `--viewport-part`
//   3. colour space  `engine.ts` — set explicitly, see the note above
//      tone mapping  `engine.ts` — ACES, which really was absent
//   4. edges         `authorDisplay`, `EdgesGeometry(geom, 25)`, depthWrite off
//   5. ground grid   `groundGridSpec` + `buildGroundGrid`, stepped off the same
//                    span `GridReadout` prints
//   6. axis triad    `components/stage/viewport/AxisTriad.tsx` — DOM, not WebGL;
//                    the reasoning is in that file's header
//   7. lights        ride with the camera, unchanged in arrangement; their
//                    intensities are retuned in `engine.ts` for ACES and the
//                    reason is written there
//
// ═══ THE TWO SCENE STATES §3.11 DOES NOT ENUMERATE ══════════════════════════
//
// **HIDDEN — authored, and deliberately absolute.** §5.4: a hidden solid's node
// is `visible = false`. The authored edges are added as **children of the mesh**
// rather than as siblings, so three.js's hierarchical visibility hides a solid's
// silhouette with the solid, for free and with no second code path. There is no
// ghost, no dimmed shell, no wireframe remnant: §5.4 says "hide", G4.5 measures
// that the mask region changed, and a ghost would be this client answering a
// question about what is in the model with a picture that says "sort of".
//
// **SELECTED — NOT AUTHORED HERE, AND THE REFUSAL IS NAMED.** There is no
// channel to author it against in this build. §4.3's spine runs *raycast hit →
// `POST /selection/resolve` → popover*, and `ProvenancePanel.tsx`:30-31 records
// that **two stations are missing**: nothing raycasts, and the resolve route is
// not served (§19 item 8, Stage 5). `WorkspaceState.selection` carries
// `{selection_id, kind, bundle_ref}` — three opaque strings with **no
// `solid_index`** — and `glb.ts` deliberately refuses to parse the ID that would
// join them to a node. So a selected-state material here would be code no data
// can reach, and the join it would need is the exact short-circuit §4.3 forbids.
// The treatment belongs with the surface that can feed it. See this item's
// report.

import type {
  BufferGeometry} from "three";
import {
  Color,
  BackSide,
  BoxGeometry,
  EdgesGeometry,
  Group,
  LineBasicMaterial,
  LineSegments,
  Mesh as ThreeMesh,
  MeshStandardMaterial,
  ShaderMaterial,
  Vector2,
  Vector3,
  type Box3,
  type Mesh,
  type Object3D,
} from "three";

/** §3.11.4, literally: `EdgesGeometry(geom, 25)`. */
export const EDGE_THRESHOLD_DEG = 25;

/** Where an overridden mesh keeps the exporter's own material. See the header. */
export const SOURCE_MATERIAL_KEY = "hephaestus_gltf_material";

/** Marks a node this module added, so a second pass can find and release it. */
export const AUTHORED_EDGES_KEY = "hephaestus_authored_edges";

/**
 * Roughness of the authored part.
 *
 * High, and metalness is zero: §3.11.7's "the picture is an instrument reading,
 * not a beauty render" is a claim about the *shading model* as much as about the
 * lights. A specular highlight is a feature of the light rig, and a reader who
 * cannot tell a highlight from a chamfer is reading the rig instead of the part.
 * What is wanted from the material is Lambert falloff — enough for a face to
 * separate from its neighbour — and nothing else.
 */
export const PART_ROUGHNESS = 0.92;

/** How many grid divisions the visible span aims to hold (§3.11.5). */
export const GRID_TARGET_DIVISIONS = 12;

/**
 * The colours this module draws with, all read from `system/tokens.css`.
 *
 * Read rather than copied, for §3.6's reason and §3.14's: a literal here would
 * fail `no-palette-token` like any other, and the ground the CSS paints and the
 * ground the clear colour paints have to be one decision.
 */
export interface ViewportPalette {
  readonly ground: Color;
  readonly part: Color;
  readonly edge: Color;
  readonly grid: Color;
  readonly gridAxis: Color;
}

/** Reads a custom property off the document root; `""` when there is no DOM. */
export type TokenReader = (name: string) => string;

/** The default reader: one `getComputedStyle` call, resolved per token. */
export function tokenReader(): TokenReader {
  if (typeof document === "undefined") return () => "";
  const style = getComputedStyle(document.documentElement);
  return (name) => style.getPropertyValue(name).trim();
}

/**
 * Resolve the six viewport tokens.
 *
 * An empty value means the stylesheet has not applied yet — the engine is
 * constructed in a layout effect and the token is a frame away. The fallbacks
 * are chosen to be *obviously* provisional rather than plausibly final: black
 * ground, white marks. `Color` cannot be constructed from `""`, so something has
 * to be chosen, and a colour that looks wrong for one frame beats a colour that
 * looks nearly right forever. Component construction (`new Color(1, 1, 1)`) is
 * used rather than a hex string so `no-palette-token` has nothing to refuse.
 */
export function readViewportPalette(read: TokenReader = tokenReader()): ViewportPalette {
  const of = (name: string, fallback: Color): Color => {
    const value = read(name);
    return value === "" ? fallback : new Color(value);
  };
  const black = (): Color => new Color(0, 0, 0);
  const white = (): Color => new Color(1, 1, 1);
  return {
    ground: of("--viewport-ground", black()),
    part: of("--viewport-part", white()),
    edge: of("--viewport-edge", white()),
    grid: of("--viewport-grid", white()),
    gridAxis: of("--viewport-grid-axis", white()),
  };
}

/** What `authorDisplay` created, so the engine can release it on the next load. */
export interface AuthoredDisplay {
  /** The one material every solid shares. */
  readonly material: MeshStandardMaterial;
  /** The one material every silhouette shares. */
  readonly edgeMaterial: LineBasicMaterial;
  /** How many meshes were overridden. */
  readonly meshes: number;
  /** How many edge sets were added — one per mesh with drawable triangles. */
  readonly edges: number;
  /** Drop the edge geometries and the two materials. Idempotent. */
  dispose(): void;
}

/**
 * §3.11.2 and §3.11.4: author the material, and add the silhouette.
 *
 * `root` is the loaded `gltf.scene`. Every `Mesh` under it — one per **face**,
 * since `gltf.py` emits one primitive per face inside its solid's mesh — is
 * given the shared authored material and gains one `LineSegments` child.
 *
 * WHY THE EDGES ARE A **CHILD OF THE MESH** and not a sibling in the solid's
 * group: the node transform is the whole of §5.2's explode (`scene.ts`
 * translates `node.object`) and the whole of §5.4's visibility. A child inherits
 * both, so an exploded solid's silhouette explodes with it and a hidden solid's
 * silhouette disappears with it — with no second traversal and no way for the
 * two to drift apart. It also means `boundsAt` and `solidCentroids`, which use
 * `setFromObject(node.object, true)`, measure the same box as before: an edge
 * line lies exactly on the surface it outlines and adds no extent.
 *
 * WHY `polygonOffset` ON THE SURFACE rather than a depth bias on the line: an
 * edge drawn at exactly its surface's depth z-fights, and the fight is per-pixel
 * and view-dependent, which is the one thing a CAD viewport may not be. Pushing
 * the *surface* back by one depth unit is the standard hidden-line construction
 * and leaves the line's own depth honest, so a line behind a nearer solid is
 * still occluded by it. `depthWrite: false` on the line is §3.11.4's own word:
 * lines do not occlude each other, so two coincident silhouettes both draw.
 *
 * Idempotent: a mesh that already carries a preserved material is left alone, so
 * a double call cannot stack two edge sets or lose the exporter's material.
 */
export function authorDisplay(root: Object3D, palette: ViewportPalette): AuthoredDisplay {
  const material = new MeshStandardMaterial({
    color: palette.part,
    roughness: PART_ROUGHNESS,
    metalness: 0,
    // `gltf.py` emits POSITION and nothing else (`:233-241` — no NORMAL
    // accessor), and the glTF spec's answer to a missing normal is flat normals.
    // For a tessellated BREP that is also the *correct* reading: a facet is a
    // facet, and smoothing them would draw a curvature the mesh does not have.
    flatShading: true,
    polygonOffset: true,
    polygonOffsetFactor: 1,
    polygonOffsetUnits: 1,
  });
  const edgeMaterial = new LineBasicMaterial({
    color: palette.edge,
    depthWrite: false,
  });

  // Collect first, mutate second: `Object3D.traverse` walks `children` live, and
  // adding a child mid-walk would visit the edge set we just created.
  const meshes: Mesh[] = [];
  root.traverse((object: Object3D) => {
    const mesh = object as Mesh;
    if (mesh.isMesh === true) meshes.push(mesh);
  });

  const geometries: BufferGeometry[] = [];
  let overridden = 0;
  for (const mesh of meshes) {
    if (mesh.userData[SOURCE_MATERIAL_KEY] !== undefined) continue;
    // PRESERVED, NOT DISPOSED. See the header: this is the exporter's
    // `baseColorFactor`, which is a selection ID, and destroying it is what the
    // review refused. Nothing reads it; it is kept because it is not ours.
    mesh.userData[SOURCE_MATERIAL_KEY] = mesh.material;
    mesh.material = material;
    overridden += 1;

    const geometry = mesh.geometry;
    const position = geometry.getAttribute("position");
    // A face the tessellator produced no triangles for has no silhouette, and
    // `EdgesGeometry` on an empty attribute set is an empty draw call rather
    // than an error. Skipping it keeps the count honest.
    if (position === undefined || position.count === 0) continue;
    const edges = new EdgesGeometry(geometry, EDGE_THRESHOLD_DEG);
    geometries.push(edges);
    const lines = new LineSegments(edges, edgeMaterial);
    lines.userData[AUTHORED_EDGES_KEY] = true;
    lines.renderOrder = 1;
    mesh.add(lines);
  }

  let disposed = false;
  return {
    material,
    edgeMaterial,
    meshes: overridden,
    edges: geometries.length,
    dispose(): void {
      if (disposed) return;
      disposed = true;
      for (const geometry of geometries) geometry.dispose();
      material.dispose();
      edgeMaterial.dispose();
    },
  };
}

/**
 * The grid step for a visible span, on the 1-2-5 ladder (§3.11.5).
 *
 * `span` is the camera's full height in model units — **exactly the number
 * `GridReadout` prints**, which is what makes §3.11.5's "so the readout finally
 * describes something visible" true rather than aspirational. The ladder is the
 * one every instrument scale uses: a step is 1, 2 or 5 times a power of ten, so
 * a division is a number a reader can multiply in their head.
 *
 * Returns 0 for a span that is not a positive finite number — there is no
 * sensible grid for an unframed camera and none is invented.
 */
export function gridStep(span: number): number {
  if (!Number.isFinite(span) || span <= 0) return 0;
  const raw = span / GRID_TARGET_DIVISIONS;
  const decade = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / decade;
  const rung = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return rung * decade;
}

/**
 * How far past the part's own footprint the pad reaches, in steps.
 *
 * THE PAD IS FINITE, AND THAT IS A DECISION WITH A TEST BEHIND IT. An unbounded
 * grid would reach the frame corners, and two assertions read a frame corner as
 * the ground: `design-system.spec.ts` samples `(4,4)` and requires it to equal
 * `--viewport-ground` byte-for-byte, and §3.11.2's floor is measured centre
 * against corner. A grid that painted a corner would turn both into assertions
 * about grid placement. It is also the better picture: a pad the part stands on
 * says where the part is; an infinite floor says where the camera is.
 *
 * THE COUPLING IS BOUNDED, NOT ELIMINATED, AND THE BOUND IS WORTH KNOWING. Both
 * of those assertions run at the fixture's default framing, where the pad
 * projects well inside the frame — the corner sample measures the ground token
 * byte for byte (`--p-slate-050` on the modeling well). Under a **top** view
 * (`+Z`) the pad is a plan of itself and necessarily reaches past a camera
 * fitted to the part, so a corner sample taken there would land on grid rather
 * than on ground. That is correct behaviour rather than a defect: a case
 * wanting the ground pixel from a top view needs a sample point chosen for it,
 * not a smaller grid.
 */
export const GRID_MARGIN_STEPS = 2;

/*
 * THE FINITE PAD IS STRUCK (2026-09-20). `GroundGridSpec`, `groundGridSpec`,
 * `GroundGrid` and `buildGroundGrid` stood here: a whole-step rectangle of
 * `LineSegments` covering the part's footprint plus `GRID_MARGIN_STEPS`, and
 * nothing else. The build space below replaces all four; see its header for
 * why the "pad is finite" decision was reversed and what survives of it.
 *
 * `GRID_MARGIN_STEPS` is kept just above, unused by any drawing code, because
 * its comment is the record of the argument that decision rested on and the
 * two assertions it constrained. Deleting the constant would delete the only
 * written account of why the frame corners used to be pure ground.
 */

/**
 * The two display flags that mutate the loaded meshes. Grid, triad and ortho
 * live on the engine / the DOM — they are not a material decision.
 *
 * `materialOverride` on means every mesh wears the one authored material at
 * `--viewport-part` (the ≥4.5:1 floor). Off restores the exporter's own
 * material, which is a selection ID, not a colour. There is no third material.
 *
 * `wireframe` on hides the fill and keeps the silhouette. The edges are
 * children of the mesh (§3.11.4), so hiding the *material* rather than the
 * *node* is what leaves the outline standing. A hidden solid (§5.4) still
 * hides both, because that is hierarchical visibility on the node.
 */
export interface DisplayAppearance {
  readonly wireframe: boolean;
  readonly materialOverride: boolean;
}

/** Collect meshes first: `traverse` walks `children` live. */
function meshesOf(root: Object3D): Mesh[] {
  const meshes: Mesh[] = [];
  root.traverse((object: Object3D) => {
    const mesh = object as Mesh;
    if (mesh.isMesh === true) meshes.push(mesh);
  });
  return meshes;
}

/**
 * Apply the operator's material / wireframe flags to an already-authored tree.
 *
 * Idempotent and order-independent with `authorDisplay`: a mesh that was never
 * authored has no `SOURCE_MATERIAL_KEY` and is left alone, so a call before
 * load is a no-op rather than a guess.
 */
export function applyAppearance(
  root: Object3D,
  authored: MeshStandardMaterial,
  appearance: DisplayAppearance,
): void {
  const meshes = meshesOf(root);
  for (const mesh of meshes) {
    const source = mesh.userData[SOURCE_MATERIAL_KEY];
    if (source === undefined) continue;
    mesh.material = appearance.materialOverride ? authored : source;
  }
  // The authored material is shared. One write covers every overridden mesh.
  authored.visible = appearance.materialOverride && !appearance.wireframe;
  for (const mesh of meshes) {
    const source = mesh.userData[SOURCE_MATERIAL_KEY] as MeshStandardMaterial | undefined;
    if (source === undefined || source === authored) continue;
    source.visible = !appearance.materialOverride && !appearance.wireframe;
  }
}

// ---------------------------------------------------------------------------
// The build space (§3.11.5, rewritten 2026-09-20)
//
// THE PAD WAS FINITE AND IS NOT ANY MORE. `GRID_MARGIN_STEPS` above still
// documents why it was: an unbounded grid reaches the frame corners, and two
// assertions read a frame corner as the ground. That reasoning was sound and
// the decision has been REVERSED ON REQUEST — the operator asked for a
// complete 3-D build space rather than a mat the part stands on, and the two
// assertions have been rewritten to sample what they were actually about.
//
// Its closing line was "a pad the part stands on says where the part is; an
// infinite floor says where the camera is". Both are true; what the request
// settles is which one this viewport is for. A CAD well is a space you build
// IN, and the floor running past the part is what gives it depth, scale and a
// horizon to read the camera against.
//
// ONE QUAD, NOT N LINE SEGMENTS. The pad drew `LineSegments` it had to rebuild
// whenever the framing changed, and lines wide enough to see up close alias
// into moiré at distance. This is a single huge quad whose fragment shader
// computes the lines in WORLD space, so:
//
//   * it costs one draw call at any extent, and nothing is rebuilt on zoom;
//   * `fwidth` gives every line the same apparent width at every distance,
//     which is what kills the moiré — the line thickens in world units exactly
//     as fast as the pixel grows in world units;
//   * the lines stay on world multiples of the step, so the line through
//     `x = 0` is still the line through `x = 0` and divisions are still
//     countable off the model origin. That was the pad's rule and it survives.
//
// THE FADE IS WHAT MAKES IT A ROOM RATHER THAN A SHEET. Alpha falls off with
// distance from the part, so the floor dissolves into `--viewport-ground`
// instead of ending on a visible edge. A hard edge at the far end of a floor
// reads as a table in a void; a fade reads as space continuing past the frame.

/** A build-space floor: where it lies and how finely it is ruled. */
export interface BuildSpaceSpec {
  /** The FINEST spacing the floor will ever draw, in model units. */
  readonly step: number;
  /** The plane the floor lies in: the scene's own floor. */
  readonly z: number;
}

/**
 * The floor's finest spacing follows the framing's `gridStep`, one decade
 * finer, because the shader only ever coarsens from here — it picks a decade
 * multiple of this at draw time, so starting a decade below the readout's step
 * leaves detail to reveal on the way in.
 */
export function buildSpaceSpec(bounds: Box3, span: number): BuildSpaceSpec | null {
  if (bounds.isEmpty()) return null;
  const step = gridStep(span);
  if (step <= 0) return null;
  // Two decades below the readout, so the shader has fine ruling to reveal
  // on the way in rather than bottoming out at the first zoom.
  return { step: step / 100, z: bounds.min.z };
}

/**
 * How many screen pixels the finest drawn spacing is held at or above.
 *
 * SMALL, because density is the depth cue. At 7 the floor read as a handful
 * of big cells and the eye had nothing to measure recession against; a
 * reference CAD space rules finely enough that the cells themselves converge.
 */
export const BUILD_SPACE_MIN_PIXELS = 4;

/**
 * Where the floor starts and finishes dissolving, as fractions of the VIEW
 * SPAN — the world-units height the viewport covers at the floor.
 *
 * Not the camera's height above the plane, which is the obvious choice and the
 * wrong one: the default camera is ORTHOGRAPHIC, and an orthographic zoom
 * changes the camera's `zoom` while leaving its position exactly where it was.
 * Sizing anything off the camera's height therefore froze the floor at one
 * extent no matter how far out the operator scrolled, which is what left a
 * hard-edged band across the middle of the well. The view span is the one
 * number that means the same thing under both projections.
 *
 * A 3:2 frame's half-diagonal is about 0.6 spans. The dissolve runs well past
 * that so the floor is at full strength across the whole frame and only
 * softens as it approaches the far walls.
 *
 * THE WALLS HAVE TO SIT INSIDE THE FADE, which is what `BUILD_SPACE_REACH`
 * below is really for. At a reach of 3 the walls stood 1.5 spans out while
 * the fade finished at 1.3, so they were erased before they were ever drawn
 * and the "room" was a floor again. The two numbers are one decision.
 */
export const BUILD_SPACE_FADE_NEAR = 1.1;
export const BUILD_SPACE_FADE_FAR = 2.9;

/**
 * The room's edge length, in view spans.
 *
 * Its walls stand at half this from the centre — 1.6 spans — which is inside
 * the dissolve above, so they read as surfaces receding into the distance
 * rather than as a box the camera is trapped in. A tighter room put the walls
 * at about one span, where they crowd the model instead of framing it.
 */
export const BUILD_SPACE_REACH = 3.2;

/** A built build space, and the handle that releases it. */
export interface BuildSpace {
  readonly object: Group;
  /**
   * Re-centre and re-scale the quad under what the camera is LOOKING AT.
   * Call each frame.
   *
   * `target` is the orbit centre, not the camera position — an iso camera
   * stands well off to the side of the thing it frames, and centring the
   * floor on it drags the bright middle of the floor off with it.
   *
   * `viewSpan` is the world-units height the viewport covers at the floor —
   * see `BUILD_SPACE_FADE_NEAR` for why it is that and not a camera height.
   */
  follow(target: Vector3, viewSpan: number): void;
  dispose(): void;
}

const BUILD_SPACE_VERTEX = /* glsl */ `
varying vec3 vWorld;
varying vec3 vNormal;
void main() {
  vec4 world = modelMatrix * vec4(position, 1.0);
  vWorld = world.xyz;
  // The box is axis-aligned and only ever uniformly scaled, so the object
  // normal IS the world normal up to sign; the fragment only uses its
  // magnitude to pick a plane, so no normal matrix is needed.
  vNormal = normal;
  gl_Position = projectionMatrix * viewMatrix * world;
}
`;

// Two ideas carry this shader, and both are about DENSITY rather than colour.
//
// 1. `fwidth(coord)` is how much a value changes across one pixel, so dividing
//    a distance-to-a-line by it converts that distance into PIXELS. Clamping
//    at 1 then draws every line exactly one pixel wide — up close and at the
//    horizon alike. That is what stops lines thinning into aliasing as they
//    recede.
//
// 2. One pixel wide does not help if the lines are half a pixel APART, which
//    is what turned the first version of this floor into a moiré band at a
//    wide zoom. So the spacing is chosen per fragment: `lod` is how many
//    decades the base step must climb for its lines to sit at least
//    `uMinPixels` apart, and the shader draws that decade and the two above
//    it, cross-fading the finest one out as it approaches the limit. Zooming
//    out therefore drops decades smoothly instead of collapsing into hatch,
//    and zooming in reveals them the same way.
const BUILD_SPACE_FRAGMENT = /* glsl */ `
precision highp float;
varying vec3 vWorld;
varying vec3 vNormal;
uniform float uStep;
uniform vec3 uLineColor;
uniform float uLineAlpha;
uniform float uWallAlpha;
uniform float uMinPixels;
uniform float uFadeNear;
uniform float uFadeFar;
uniform vec2 uCentre;

// One pixel wide at any distance: dividing the distance-to-a-line by
// fwidth(coord) converts it into PIXELS, and clamping at 1 draws it one pixel
// wide up close and at the horizon alike.
float lineMask(vec2 p, float spacing) {
  vec2 coord = p / spacing;
  vec2 grid = abs(fract(coord - 0.5) - 0.5) / fwidth(coord);
  return 1.0 - min(min(grid.x, grid.y), 1.0);
}

void main() {
  // WHICH FACE AM I ON. The build space is a box seen from the inside, so the
  // grid is drawn in the two axes lying IN this face — that is what makes the
  // lines meet at the corners instead of sliding across them.
  vec3 n = abs(vNormal);
  vec2 p;
  if (n.z > n.x && n.z > n.y) p = vWorld.xy;
  else if (n.y > n.x) p = vWorld.xz;
  else p = vWorld.yz;

  float fade = 1.0 - smoothstep(uFadeNear, uFadeFar, distance(vWorld, vec3(uCentre, vWorld.z)));
  if (fade <= 0.0) discard;

  // ONE GRID, ONE WEIGHT (rewritten 2026-09-20).
  //
  // This drew three decades at two different strengths plus a highlighted
  // datum line through the origin. Three things were wrong with that and all
  // three were visible: the datum lines were bright enough to read as part of
  // the MODEL and crossed straight through it; the major/minor split made the
  // floor look like graph paper rather than a surface; and the decade
  // hand-over was a visible change of pattern, so zooming out "degraded"
  // instead of continuing.
  //
  // A reference CAD space draws one uniform ruling and lets DENSITY carry the
  // depth. So: one spacing, one alpha, and the only thing the level of detail
  // does is cross-fade between adjacent decades so the hand-over cannot be
  // seen. fine is a decade above the pixel floor and fades OUT as it
  // approaches it, while coarse — already on screen at full strength — takes
  // over. At every moment the two sum to one grid.
  float perPixel = max(fwidth(p.x), fwidth(p.y));
  float lod = max(-1.0, log2(perPixel * uMinPixels / uStep) / log2(10.0));
  float rung = floor(lod);
  float climb = lod - rung;

  float fine = uStep * pow(10.0, rung + 1.0);
  float coarse = fine * 10.0;

  float alpha = max(lineMask(p, fine) * (1.0 - climb), lineMask(p, coarse));
  alpha *= uLineAlpha * fade * ((n.z > n.x && n.z > n.y) ? 1.0 : uWallAlpha);
  if (alpha < 0.004) discard;
  gl_FragColor = vec4(uLineColor, alpha);
}
`;

/**
 * Build the floor as one shaded quad that follows the camera.
 *
 * THE QUAD IS NOT THE FLOOR'S EXTENT. Its lines are computed from WORLD
 * position, so sliding the quad under the camera does not slide the grid — the
 * line through `x = 0` stays the line through `x = 0`. The quad is only a
 * canvas big enough to cover the view, which is why `follow` may move and
 * resize it freely and why the floor reads as unbounded without ever being a
 * geometry large enough to lose float precision.
 *
 * `depthWrite: false` for the reason the pad it replaced had it: the floor is
 * a reference mark, and a mark that occludes the part it is a reference for
 * has the priority backwards. It still TESTS depth, so the part hides the
 * floor behind it — which is what makes this read as a floor and not an
 * overlay.
 *
 * `BackSide` because the space is a box seen from INSIDE: the near faces are
 * culled, so every camera sees the three far ones and never the box itself.
 * Orbiting under the part now means looking up at the ceiling, which is a
 * room rather than a hole.
 */
export function buildBuildSpace(spec: BuildSpaceSpec, palette: ViewportPalette): BuildSpace {
  // A BOX SEEN FROM THE INSIDE (2026-09-20), not a floor.
  //
  // The space was one quad in the ground plane, which is a mat: it gives the
  // part something to stand on and tells you nothing about the volume around
  // it. A room does — the walls converging behind the model are what make an
  // orbit read as an orbit, and they are the difference between a drawing and
  // a space. `BackSide` is the whole trick: the near faces are culled, so
  // from any camera you see the three far ones and never the box itself.
  const geometry = new BoxGeometry(1, 1, 1);
  const material = new ShaderMaterial({
    vertexShader: BUILD_SPACE_VERTEX,
    fragmentShader: BUILD_SPACE_FRAGMENT,
    uniforms: {
      uStep: { value: spec.step },
      uLineColor: { value: new Vector3(palette.grid.r, palette.grid.g, palette.grid.b) },
      // One weight for the whole ruling. Low, because DENSITY is the depth
      // cue here, not contrast — a grid you read line by line competes with
      // the geometry standing on it.
      uLineAlpha: { value: 0.5 },
      uWallAlpha: { value: 0.6 },
      uMinPixels: { value: BUILD_SPACE_MIN_PIXELS },
      uFadeNear: { value: 0 },
      uFadeFar: { value: 0 },
      uCentre: { value: new Vector2() },
    },
    transparent: true,
    depthWrite: false,
    // Only the far faces. `FrontSide` would put a lid over the camera.
    side: BackSide,
  });

  const mesh = new ThreeMesh(geometry, material);
  mesh.position.set(0, 0, spec.z);
  // Drawn before the part so its blend lands under the solid, and off the
  // raycaster: the floor is scenery, never a pick target.
  mesh.renderOrder = -1;
  mesh.raycast = () => undefined;
  // The quad moves every frame, so its own bounds are never a reason to cull
  // it — three would otherwise test yesterday's sphere against today's camera.
  mesh.frustumCulled = false;

  const object = new Group();
  object.add(mesh);

  let disposed = false;
  return {
    object,
    follow(target: Vector3, viewSpan: number): void {
      if (disposed) return;
      const span = Number.isFinite(viewSpan) && viewSpan > 0 ? viewSpan : spec.step;
      const reach = span * BUILD_SPACE_REACH;
      // The box SITS ON the scene floor rather than centring on the target:
      // its bottom face is the ground the part stands on, so the centre is
      // half a box above it. Horizontally it follows the target, which is
      // what keeps the walls behind whatever the camera is looking at.
      mesh.position.set(target.x, target.y, spec.z + reach / 2);
      mesh.scale.set(reach, reach, reach);
      const centre = material.uniforms["uCentre"]?.value as Vector2 | undefined;
      centre?.set(target.x, target.y);
      const near = material.uniforms["uFadeNear"];
      const far = material.uniforms["uFadeFar"];
      if (near !== undefined) near.value = span * BUILD_SPACE_FADE_NEAR;
      if (far !== undefined) far.value = span * BUILD_SPACE_FADE_FAR;
    },
    dispose(): void {
      if (disposed) return;
      disposed = true;
      geometry.dispose();
      material.dispose();
    },
  };
}
