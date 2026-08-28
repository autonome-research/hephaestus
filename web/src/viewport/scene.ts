// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Scene-graph operations over the loaded GLB (INTERFACE.md §5.2, §5.4, §5.5).
//
// Everything here is what §1 hands the client outright: "camera transforms,
// raycast hits, **per-node visibility**, **per-node translation along a
// server-declared axis**". Nothing here computes a value that reaches a result,
// a badge, a readout, a provenance answer, or a selection — the one function
// that returns positions (`solidCentroids`) exists for the *test harness* and
// says so on itself.
//
// **No WebGL.** Every function takes plain three.js objects (`Object3D`, `Box3`,
// `OrthographicCamera`) and is therefore exercisable in vitest under jsdom; the
// renderer, the canvas, and the animation loop live in the component. That split
// is why §5.2's transform and §5.4's visibility rule have unit tests at all.
//
// THE NODE ↔ MESH MAPPING, and why it is read from the loader rather than
// assumed. `core/render/gltf.py` emits one node per mesh in mesh order, so
// `scene.children[i]` *is* mesh `i` today. Relying on that would make this file
// depend on an emission order no test pins. `GLTFLoader` records the real
// mapping in `parser.associations` (an `Object3D → {meshes, primitives}` map),
// and a mesh with several primitives arrives as a `Group` whose association
// carries `meshes` alone. Reading the association is the same fact from the
// party that actually built the tree.

import { Box3, Vector3, type Object3D, type OrthographicCamera, type Plane } from "three";
import type { GLTF } from "three/addons/loaders/GLTFLoader.js";
import { eyeDirection, upHint, viewAngles } from "./cameras";
import { explodeTranslation, type Displacement } from "./explode";
import type { GlbGeometry, GlbSolid } from "./glb";

/** One solid, joined to the object that carries it in the loaded scene. */
export interface SolidNode {
  readonly solid: GlbSolid;
  /** The scene-graph node for this mesh: a `Mesh`, or a `Group` of primitives. */
  readonly object: Object3D;
}

/** Everything the viewport holds about one loaded GLB. */
export interface SolidIndex {
  readonly nodes: readonly SolidNode[];
  /** By `solid_index`, which is the key the Results list and the passes use. */
  readonly bySolid: ReadonlyMap<number, SolidNode>;
  /** By `mesh_index`, which is the key a raycast hint carries (§12.3). */
  readonly byMesh: ReadonlyMap<number, SolidNode>;
}

interface Association {
  readonly meshes?: number;
  readonly primitives?: number;
}

/**
 * Join the parsed GLB document to the loaded scene graph.
 *
 * A mesh the loader did not materialise (every primitive empty) is **left out
 * rather than faked**: a row with no node cannot be hidden or exploded, and a
 * placeholder object would make the visibility toggle silently do nothing.
 */
export function indexSolidNodes(gltf: GLTF, geometry: GlbGeometry): SolidIndex {
  const associations = gltf.parser.associations as Map<Object3D, Association>;
  const objectByMesh = new Map<number, Object3D>();
  for (const child of gltf.scene.children) {
    const association = associations.get(child);
    const meshIndex = association?.meshes;
    if (typeof meshIndex === "number" && !objectByMesh.has(meshIndex)) {
      objectByMesh.set(meshIndex, child);
    }
  }

  const nodes: SolidNode[] = [];
  const bySolid = new Map<number, SolidNode>();
  const byMesh = new Map<number, SolidNode>();
  for (const solid of geometry.solids) {
    const object = objectByMesh.get(solid.mesh_index);
    if (object === undefined) continue;
    const node: SolidNode = { solid, object };
    nodes.push(node);
    bySolid.set(solid.solid_index, node);
    byMesh.set(solid.mesh_index, node);
  }
  return { nodes, bySolid, byMesh };
}

/**
 * §5.2: "the client translates each solid's node by `explode_offset · t`".
 *
 * The GLB's vertices are baked in world coordinates under identity node
 * transforms, so the node's position *is* the displacement — there is no
 * accumulated transform to compose with and none is composed.
 */
export function applyExplode(index: SolidIndex, t: number): void {
  for (const node of index.nodes) {
    const [x, y, z] = explodeTranslation(node.solid.explode_offset, t);
    node.object.position.set(x, y, z);
    node.object.updateMatrixWorld(true);
  }
}

/**
 * §5.4: "hide the corresponding GLTF mesh node — a scene-graph property, not
 * geometry."
 *
 * `hidden` holds **geometry-entry labels**, which `state/visibility.ts` explains
 * is "the only namespace `GET /parts/{part}/build` gives the client". The join
 * needs nothing computed here: `inspect.py::build_solid_labels` maps each solid
 * index to its entry's label server-side and `gltf.py` writes the result into
 * each mesh's `extras.label`, so hiding a label hides exactly the meshes the
 * server says that entry owns. Where an entry covers several solids the toggle
 * covers the group, which is what the Results panel tells the reader it does.
 *
 * A mesh with **no** label is never hidden: there is no row that could have
 * asked for it, and hiding an unnamed node on a name match would be a guess.
 */
export function applyVisibility(index: SolidIndex, hidden: ReadonlySet<string>): void {
  for (const node of index.nodes) {
    const label = node.solid.label;
    node.object.visible = label === null || !hidden.has(label);
  }
}

/** Set the clipping planes on every material under `root` (§5.3's preview). */
export function applyClipping(root: Object3D, planes: readonly Plane[]): void {
  root.traverse((object: Object3D) => {
    const material = (object as { material?: unknown }).material;
    for (const entry of Array.isArray(material) ? material : material === undefined ? [] : [material]) {
      const target = entry as { clippingPlanes?: readonly Plane[] | null; needsUpdate?: boolean };
      target.clippingPlanes = planes.length === 0 ? null : [...planes];
      target.needsUpdate = true;
    }
  });
}

/**
 * The scene's bounds with each solid displaced by `explode_offset · t`.
 *
 * WHICH `t` THE CAMERA FRAMES TO, and why it is not always 1.
 * `channels.py::_framing` (`:609-618`) makes this decision server-side and makes
 * it **per channel**: the `explode` channel frames once to the fully-exploded
 * extent "so the projected scale is constant across t"; `rgb`, `mask` and
 * `section` frame to the plain scene bbox. The viewport is a peer of all four,
 * and G4.5 requires its screenshots be taken "at the pass's own resolution **and
 * camera**" — a mask pass is framed to the plain bbox. So the viewport frames to
 * the plain bbox while `explode_t === 0` and to the `t = 1` extent once explode
 * is engaged, which is exactly what the server does for the channel each state
 * corresponds to.
 *
 * §5.2's "framed once and held" is untouched: the framing changes only when
 * explode *engages* or *disengages*, never between two non-zero `t` values, so
 * no drag re-fits the camera and the projected scale is constant across the
 * whole of it.
 */
export function boundsAt(index: SolidIndex, t: number): Box3 {
  const bounds = new Box3();
  const solidBox = new Box3();
  const offset = new Vector3();
  for (const node of index.nodes) {
    const displacement: Displacement = explodeTranslation(node.solid.explode_offset, t);
    // Measure each node in its *undisplaced* pose, then translate the box, so
    // the answer does not depend on the slider's current position.
    const saved = node.object.position.clone();
    node.object.position.set(0, 0, 0);
    node.object.updateMatrixWorld(true);
    solidBox.setFromObject(node.object, true);
    node.object.position.copy(saved);
    node.object.updateMatrixWorld(true);
    if (solidBox.isEmpty()) continue;
    offset.set(displacement[0], displacement[1], displacement[2]);
    bounds.union(solidBox.translate(offset));
  }
  return bounds;
}

/** The framing an orthographic camera needs to hold `bounds` for one view. */
export interface Framing {
  readonly eye: readonly [number, number, number];
  readonly target: readonly [number, number, number];
  readonly up: readonly [number, number, number];
  /** Half-extents, already fitted to the viewport aspect (never stretched). */
  readonly halfWidth: number;
  readonly halfHeight: number;
  readonly near: number;
  readonly far: number;
}

/** `cameras.py::DEFAULT_MARGIN` — the same 5 % breathing room the server uses. */
export const FRAMING_MARGIN = 1.05;

/**
 * Fit an orthographic camera to `bounds` for `view`, mirroring
 * `cameras.py::camera_framing`'s construction: eye on the view direction at a
 * distance clearing the box, half-extents from the projected corner radius grown
 * to the viewport aspect, then the margin.
 */
export function framingFor(bounds: Box3, view: string, aspect: number): Framing | null {
  const angles = viewAngles(view);
  if (angles === null || bounds.isEmpty() || !(aspect > 0)) return null;

  const centre = bounds.getCenter(new Vector3());
  const size = bounds.getSize(new Vector3());
  const direction = eyeDirection(angles);
  const up = upHint(direction);
  const diagonal = size.length();
  const distance = diagonal + 1;

  const forward = new Vector3(direction[0], direction[1], direction[2]).normalize();
  const upVector = new Vector3(up[0], up[1], up[2]);
  const right = new Vector3().crossVectors(upVector, forward).normalize();
  const trueUp = new Vector3().crossVectors(forward, right).normalize();

  let halfU = 0;
  let halfV = 0;
  let halfW = 0;
  const corner = new Vector3();
  for (const x of [bounds.min.x, bounds.max.x]) {
    for (const y of [bounds.min.y, bounds.max.y]) {
      for (const z of [bounds.min.z, bounds.max.z]) {
        corner.set(x, y, z).sub(centre);
        halfU = Math.max(halfU, Math.abs(corner.dot(right)));
        halfV = Math.max(halfV, Math.abs(corner.dot(trueUp)));
        halfW = Math.max(halfW, Math.abs(corner.dot(forward)));
      }
    }
  }
  if (halfU <= 0) halfU = 1;
  if (halfV <= 0) halfV = 1;

  if (halfU / halfV < aspect) halfU = halfV * aspect;
  else halfV = halfU / aspect;

  return {
    eye: [
      centre.x + forward.x * distance,
      centre.y + forward.y * distance,
      centre.z + forward.z * distance,
    ],
    target: [centre.x, centre.y, centre.z],
    up: [trueUp.x, trueUp.y, trueUp.z],
    halfWidth: halfU * FRAMING_MARGIN,
    halfHeight: halfV * FRAMING_MARGIN,
    near: Math.max(distance - halfW - 1, 0.01),
    far: distance + halfW + 1,
  };
}

/** Point `camera` at `framing` without changing its zoom-independent extents. */
export function applyFraming(camera: OrthographicCamera, framing: Framing): void {
  camera.position.set(framing.eye[0], framing.eye[1], framing.eye[2]);
  camera.up.set(framing.up[0], framing.up[1], framing.up[2]);
  camera.left = -framing.halfWidth;
  camera.right = framing.halfWidth;
  camera.top = framing.halfHeight;
  camera.bottom = -framing.halfHeight;
  camera.near = framing.near;
  camera.far = framing.far;
  camera.lookAt(framing.target[0], framing.target[1], framing.target[2]);
  camera.updateProjectionMatrix();
  camera.updateMatrixWorld(true);
}

/**
 * World-space bounding-box centres, keyed by `solid_index`.
 *
 * **This is a test-harness reading, not a workspace value.** G4.6 "reads
 * pairwise centroid distances back out of the scene graph" (§5.2), which is a
 * screen-space fact about a server-declared vector — §1 exempts exactly that,
 * *and* forbids the client presenting a distance as fact. So this function
 * returns positions and never distances, nothing in `web/src` renders its
 * output, and the only caller is the debug handle in `testHook.ts`. The
 * subtraction G4.6 actually asserts on happens in the Playwright harness.
 */
export function solidCentroids(index: SolidIndex): Map<number, [number, number, number]> {
  const out = new Map<number, [number, number, number]>();
  const box = new Box3();
  const centre = new Vector3();
  for (const node of index.nodes) {
    node.object.updateMatrixWorld(true);
    box.setFromObject(node.object, true);
    if (box.isEmpty()) continue;
    box.getCenter(centre);
    out.set(node.solid.solid_index, [centre.x, centre.y, centre.z]);
  }
  return out;
}
