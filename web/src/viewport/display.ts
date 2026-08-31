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

import {
  BufferGeometry,
  Color,
  EdgesGeometry,
  Float32BufferAttribute,
  Group,
  LineBasicMaterial,
  LineSegments,
  MeshStandardMaterial,
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

/** A ground grid, in model units, resolved to whole steps. */
export interface GroundGridSpec {
  readonly step: number;
  /** The plane the grid lies in: the scene's own floor. */
  readonly z: number;
  readonly minX: number;
  readonly maxX: number;
  readonly minY: number;
  readonly maxY: number;
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

/**
 * The grid for `bounds` at a camera span, or `null` when there is nothing to
 * stand on.
 *
 * Lines land on **world multiples of the step**, not on multiples measured from
 * the part's corner, so the line through `x = 0` is a line through `x = 0` and a
 * reader can count divisions off the model origin. The pad is then the smallest
 * whole-step rectangle that covers the part's XY footprint plus
 * `GRID_MARGIN_STEPS` on each side.
 */
export function groundGridSpec(bounds: Box3, span: number): GroundGridSpec | null {
  if (bounds.isEmpty()) return null;
  const step = gridStep(span);
  if (step <= 0) return null;
  const pad = GRID_MARGIN_STEPS * step;
  return {
    step,
    z: bounds.min.z,
    minX: Math.floor((bounds.min.x - pad) / step) * step,
    maxX: Math.ceil((bounds.max.x + pad) / step) * step,
    minY: Math.floor((bounds.min.y - pad) / step) * step,
    maxY: Math.ceil((bounds.max.y + pad) / step) * step,
  };
}

/** A built grid, and the handle that releases its two geometries. */
export interface GroundGrid {
  readonly object: Group;
  readonly lines: number;
  dispose(): void;
}

/**
 * Build §3.11.5's ground grid as two draw calls.
 *
 * Two, because the grid says two different things: the **minor** lines are a
 * ruler, and the two lines through the model origin are a datum. They are
 * separate `LineSegments` so they can carry separate tokens, which is the same
 * split `--border` and `--border-strong` already make in CSS.
 *
 * `depthWrite: false` for the same reason as the silhouette: the grid is a
 * reference mark, and a mark that occludes the part it is a reference for has
 * the priority backwards. It still *tests* depth, so the part hides the grid
 * behind it — which is what makes the pad read as a floor rather than as an
 * overlay.
 */
export function buildGroundGrid(spec: GroundGridSpec, palette: ViewportPalette): GroundGrid {
  const minor: number[] = [];
  const datum: number[] = [];
  const { step, z, minX, maxX, minY, maxY } = spec;

  // `Math.round` on the division index rather than accumulating `+= step`:
  // accumulating floating-point steps across a hundred divisions drifts, and a
  // grid whose last line is a third of a millimetre off is a grid that lies.
  const columns = Math.round((maxX - minX) / step);
  const rows = Math.round((maxY - minY) / step);
  for (let i = 0; i <= columns; i += 1) {
    const x = minX + i * step;
    const into = Math.abs(x) < step / 2 ? datum : minor;
    into.push(x, minY, z, x, maxY, z);
  }
  for (let j = 0; j <= rows; j += 1) {
    const y = minY + j * step;
    const into = Math.abs(y) < step / 2 ? datum : minor;
    into.push(minX, y, z, maxX, y, z);
  }

  const object = new Group();
  const geometries: BufferGeometry[] = [];
  const materials: LineBasicMaterial[] = [];
  const add = (points: readonly number[], colour: Color): void => {
    if (points.length === 0) return;
    const geometry = new BufferGeometry();
    geometry.setAttribute("position", new Float32BufferAttribute(Array.from(points), 3));
    const material = new LineBasicMaterial({ color: colour, depthWrite: false });
    geometries.push(geometry);
    materials.push(material);
    object.add(new LineSegments(geometry, material));
  };
  add(minor, palette.grid);
  add(datum, palette.gridAxis);

  let disposed = false;
  return {
    object,
    lines: (minor.length + datum.length) / 6,
    dispose(): void {
      if (disposed) return;
      disposed = true;
      for (const geometry of geometries) geometry.dispose();
      for (const material of materials) material.dispose();
    },
  };
}

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
