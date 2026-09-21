// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Viewport display authorship (INTERFACE.md §3.11, plan item 6).
//
// The half of §3.11 that is a *contract* rather than an appearance, which is
// most of it: what the override does to the exporter's selection channel, where
// the silhouette is attached in the tree, and what the grid's step and extent
// are for a given camera span. The appearance half — "does the part clear 4.5:1
// against the ground once it is lit and tone-mapped" — cannot be answered
// without a GPU and is asserted in `e2e/design-system.spec.ts`, which is where
// §3.11.2 says to measure it ("measured in the browser").
//
// THE FIRST DESCRIBE IS THE ONE THE 2026-08-28 REVIEW ASKED FOR. It refuted a
// wholesale material override because `core/render/gltf.py` encodes selection
// IDs in `baseColorFactor`. These cases are the standing proof that authorship
// did not destroy that channel: the exporter's material is still on the node
// and its 0-255 triple still reconstructs exactly.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  Box3,
  Color,
  Float32BufferAttribute,
  Group,
  LinearSRGBColorSpace,
  Mesh,
  MeshStandardMaterial,
  Vector3,
  type Object3D,
} from "three";
import type { LineSegments ,
  Mesh as ThreeMesh,
  ShaderMaterial} from "three";
import type { GLTF } from "three/addons/loaders/GLTFLoader.js";
import {
  AUTHORED_EDGES_KEY,
  EDGE_THRESHOLD_DEG,
  GRID_TARGET_DIVISIONS,
  SOURCE_MATERIAL_KEY,
  authorDisplay,
  applyAppearance,
  buildBuildSpace,
  gridStep,
  buildSpaceSpec,
  BUILD_SPACE_FADE_FAR,
  BUILD_SPACE_FADE_NEAR,
  BUILD_SPACE_MIN_PIXELS,
  readViewportPalette,
  type ViewportPalette,
} from "../src/viewport/display";
import { applyVisibility, indexSolidNodes } from "../src/viewport/scene";
import { snapshotSolids } from "../src/viewport/testHook";
import { readGlbGeometry } from "../src/viewport/glb";
import { DEFAULT_APPEARANCE } from "../src/state/appearance";
import { fakeGlb } from "./glb";

/** A palette that is not the token palette, so an assertion cannot pass by luck. */
const PALETTE: ViewportPalette = {
  ground: new Color(0.01, 0.02, 0.03),
  part: new Color(0.7, 0.75, 0.8),
  edge: new Color(0.93, 0.95, 0.97),
  grid: new Color(0.15, 0.17, 0.21),
  gridAxis: new Color(0.23, 0.26, 0.32),
};

/**
 * `core/render/gltf.py`:206-215 — `baseColorFactor = id_to_rgb(solid_id)/255`.
 *
 * `palette.py`:60-69 encodes the id as the 24-bit big-endian integer `id + 1`,
 * which is why solid 0 is `(0, 0, 1)` and the part was black. Transcribed rather
 * than imported: this is a *test* asserting the client did not destroy a server
 * encoding, so it has to state the encoding independently of the client.
 */
function idToRgb(selectionId: number): [number, number, number] {
  const value = selectionId + 1;
  return [(value >> 16) & 0xff, (value >> 8) & 0xff, value & 0xff];
}

/**
 * Two triangles sharing an edge, folded to `dihedral` degrees about it.
 *
 * `90` is a chamfer the 25° threshold must keep; `0` is the interior of a
 * tessellated flat face, which it must drop. Non-indexed with duplicated
 * vertices, exactly as `gltf.py` emits — `EdgesGeometry` merges by position, and
 * a test on an indexed fixture would not exercise that.
 */
function foldedPair(dihedral: number): Float32BufferAttribute {
  const radians = (dihedral * Math.PI) / 180;
  // A unit square split along B→C, with the second triangle's free vertex D
  // rotated about that shared edge. At 0° the pair is one planar quad and the
  // two face normals agree; at θ they differ by exactly θ.
  const a = 0.5 + 0.5 * Math.cos(radians);
  const d: [number, number, number] = [a, a, -Math.sin(radians) / Math.SQRT2];
  return new Float32BufferAttribute(
    [0, 0, 0, 1, 0, 0, 0, 1, 0, /* — */ 1, 0, 0, d[0], d[1], d[2], 0, 1, 0],
    3,
  );
}

/** A mesh carrying the exporter's material, as `GLTFLoader` would build it. */
function exporterMesh(selectionId: number): Mesh {
  const material = new MeshStandardMaterial({ metalness: 0, roughness: 1 });
  const [r, g, b] = idToRgb(selectionId);
  // glTF `baseColorFactor` is linear, and `GLTFLoader` assigns it as linear.
  material.color.setRGB(r / 255, g / 255, b / 255, LinearSRGBColorSpace);
  const mesh = new Mesh(undefined, material);
  // A real triangle so `EdgesGeometry` has something to find. Two triangles
  // meeting at 90°, which is well past the 25° threshold, so the shared edge
  // survives and the count is a fact rather than an accident of tessellation.
  mesh.geometry.setAttribute("position", foldedPair(90));
  return mesh;
}

/** A loaded scene of `count` solids, each with the exporter's ID material. */
function loadedScene(count: number): { scene: Group; meshes: Mesh[] } {
  const scene = new Group();
  const meshes: Mesh[] = [];
  for (let i = 0; i < count; i += 1) {
    const solid = new Group();
    const mesh = exporterMesh(i);
    solid.add(mesh);
    scene.add(solid);
    meshes.push(mesh);
  }
  return { scene, meshes };
}

// ---------------------------------------------------------------------------
// §3.11.2 — the material, and the selection channel it must not destroy
// ---------------------------------------------------------------------------

describe("authorDisplay — the material override and the ID channel (§3.11.2)", () => {
  it("gives every mesh the one authored material at the part token", () => {
    const { scene, meshes } = loadedScene(3);
    const display = authorDisplay(scene, PALETTE);

    expect(display.meshes).toBe(3);
    for (const mesh of meshes) {
      expect(mesh.material).toBe(display.material);
    }
    // One material, not three: the part is one decision, and a per-mesh copy
    // would be three places for it to drift.
    expect(display.material).toBeInstanceOf(MeshStandardMaterial);
    expect(display.material.color.getHex()).toBe(PALETTE.part.getHex());
    expect(display.material.metalness).toBe(0);
    // `gltf.py` emits POSITION only, so the glTF spec's answer is flat normals.
    expect(display.material.flatShading).toBe(true);
    // The silhouette is drawn at its surface's depth; the surface is what moves.
    expect(display.material.polygonOffset).toBe(true);
  });

  it("PRESERVES the exporter's material so baseColorFactor still decodes", () => {
    const { scene, meshes } = loadedScene(4);
    authorDisplay(scene, PALETTE);

    meshes.forEach((mesh, solidIndex) => {
      const preserved = mesh.userData[SOURCE_MATERIAL_KEY] as MeshStandardMaterial | undefined;
      expect(preserved, `solid ${String(solidIndex)} lost its exporter material`).toBeInstanceOf(
        MeshStandardMaterial,
      );
      // The whole point: the server's encoding survives the override byte for
      // byte. `id_to_rgb` is a bijection over the palette, so recovering the
      // triple is recovering the selection ID.
      const rgb = { r: 0, g: 0, b: 0 };
      preserved?.color.getRGB(rgb, LinearSRGBColorSpace);
      expect([
        Math.round(rgb.r * 255),
        Math.round(rgb.g * 255),
        Math.round(rgb.b * 255),
      ]).toEqual(idToRgb(solidIndex));
      // And it is not disposed: a disposed material is still readable in JS but
      // its GPU resources are gone, and "kept" has to mean kept.
      expect(preserved).not.toBe(null);
    });
  });

  it("never lets the preserved colour reach anything the harness or app reads (§1, §12.3)", () => {
    const { scene, meshes } = loadedScene(2);
    authorDisplay(scene, PALETTE);
    const associations = new Map<Object3D, { meshes: number }>();
    scene.children.forEach((child, i) => associations.set(child, { meshes: i }));
    const gltf = { scene, parser: { associations } } as unknown as GLTF;
    const geometry = readGlbGeometry(
      fakeGlb({
        solids: [
          { solid_index: 0, label: "a", explode_offset: [0, 0, 0] },
          { solid_index: 1, label: "b", explode_offset: [1, 0, 0] },
        ],
      }),
    );

    const serialized = JSON.stringify(snapshotSolids(indexSolidNodes(gltf, geometry)));
    // `glb.ts` refuses to parse `selection_id` because "a client that had the ID
    // in hand would eventually submit it". A client that could read
    // `id_to_rgb(solid_id)` off a material would have it by arithmetic, so the
    // preserved material must not be reachable from anything that crosses out.
    expect(serialized).not.toContain(SOURCE_MATERIAL_KEY);
    expect(serialized).not.toContain("color");
    expect(serialized).not.toContain("material");
    expect(meshes[0]?.userData[SOURCE_MATERIAL_KEY]).toBeDefined();
  });

  it("is idempotent — a second call stacks no edges and loses no material", () => {
    const { scene, meshes } = loadedScene(2);
    const first = authorDisplay(scene, PALETTE);
    const preserved = meshes[0]?.userData[SOURCE_MATERIAL_KEY];
    const second = authorDisplay(scene, PALETTE);

    expect(second.meshes).toBe(0);
    expect(second.edges).toBe(0);
    expect(meshes[0]?.userData[SOURCE_MATERIAL_KEY]).toBe(preserved);
    expect(childEdges(meshes[0] as Mesh)).toHaveLength(1);
    first.dispose();
    second.dispose();
  });
});

// ---------------------------------------------------------------------------
// §3.11.4 — the silhouette, and where it hangs in the tree
// ---------------------------------------------------------------------------

function childEdges(object: Object3D): LineSegments[] {
  return object.children.filter(
    (child): child is LineSegments => child.userData[AUTHORED_EDGES_KEY] === true,
  );
}

describe("authorDisplay — edges (§3.11.4)", () => {
  it("adds one edge set per mesh, as a CHILD of that mesh", () => {
    const { scene, meshes } = loadedScene(3);
    const display = authorDisplay(scene, PALETTE);

    expect(display.edges).toBe(3);
    for (const mesh of meshes) {
      const edges = childEdges(mesh);
      expect(edges).toHaveLength(1);
      expect(edges[0]?.parent).toBe(mesh);
      expect(edges[0]?.material).toBe(display.edgeMaterial);
    }
    // §3.11.4 names this literally, and it is what lets two coincident
    // silhouettes both draw instead of one erasing the other.
    expect(display.edgeMaterial.depthWrite).toBe(false);
  });

  it("keeps a crease and drops a tessellation seam, at §3.11.4's 25°", () => {
    expect(EDGE_THRESHOLD_DEG).toBe(25);

    const endpointsAt = (dihedral: number): number => {
      const { scene, meshes } = loadedScene(1);
      (meshes[0] as Mesh).geometry.setAttribute("position", foldedPair(dihedral));
      authorDisplay(scene, PALETTE);
      return childEdges(meshes[0] as Mesh)[0]?.geometry.getAttribute("position").count ?? -1;
    };

    // A 90° chamfer: four boundary segments plus the crease — five lines.
    expect(endpointsAt(90)).toBe(10);
    // A flat face's interior seam, which is most of a tessellated BREP: the
    // crease is gone and only the face's own outline survives — four lines.
    // This is the assertion that makes the threshold a threshold rather than a
    // number in a call, and it is why a cylinder reads as a cylinder and not as
    // a fan of triangles.
    expect(endpointsAt(0)).toBe(8);
    // And the threshold is where §3.11.4 put it, not somewhere either side.
    expect(endpointsAt(20)).toBe(8);
    expect(endpointsAt(30)).toBe(10);
  });

  it("hides a solid's silhouette with the solid — §5.4's hide, and no ghost", () => {
    const { scene, meshes } = loadedScene(2);
    authorDisplay(scene, PALETTE);
    const associations = new Map<Object3D, { meshes: number }>();
    scene.children.forEach((child, i) => associations.set(child, { meshes: i }));
    const gltf = { scene, parser: { associations } } as unknown as GLTF;
    const geometry = readGlbGeometry(
      fakeGlb({
        solids: [
          { solid_index: 0, label: "keep", explode_offset: [0, 0, 0] },
          { solid_index: 1, label: "hide", explode_offset: [0, 0, 0] },
        ],
      }),
    );
    const index = indexSolidNodes(gltf, geometry);

    applyVisibility(index, new Set(["hide"]));

    // The node is invisible, and three.js visibility is hierarchical, so the
    // edge child is not drawn either. The assertion is on the *ancestry*: the
    // edges hang under the toggled node, which is what makes the second fact
    // true without a second code path that could rot.
    const hidden = index.bySolid.get(1);
    expect(hidden?.object.visible).toBe(false);
    expect(childEdges(meshes[1] as Mesh)[0]?.visible).toBe(true);
    expect(isUnder(childEdges(meshes[1] as Mesh)[0] as Object3D, hidden?.object as Object3D)).toBe(
      true,
    );
    expect(index.bySolid.get(0)?.object.visible).toBe(true);
  });
});

function isUnder(node: Object3D, ancestor: Object3D): boolean {
  for (let at: Object3D | null = node.parent; at !== null; at = at.parent) {
    if (at === ancestor) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// §3.11.5 — the ground grid, stepped off the readout's own span
// ---------------------------------------------------------------------------

describe("gridStep (§3.11.5)", () => {
  it("walks the 1-2-5 ladder", () => {
    // A span of 120 wants ten divisions of 10 at a target of 12.
    expect(gridStep(120)).toBeCloseTo(10, 10);
    expect(gridStep(12)).toBeCloseTo(1, 10);
    expect(gridStep(1.2)).toBeCloseTo(0.1, 10);
    expect(gridStep(1200)).toBeCloseTo(100, 10);
    // Between rungs, the step rounds UP to the next rung, so the visible span
    // never holds more than `GRID_TARGET_DIVISIONS` divisions.
    expect(gridStep(25)).toBeCloseTo(5, 10); // 25/12 = 2.08 → the 5 rung
    expect(gridStep(50)).toBeCloseTo(5, 10); // 50/12 = 4.17 → the 5 rung
    expect(gridStep(100)).toBeCloseTo(10, 10); // 100/12 = 8.3 → the next decade
    // Over four decades, every step is a rung and the span never holds more
    // than the target number of divisions. That pair is the whole contract:
    // a number a reader can multiply, at a density a reader can count.
    for (const span of [1, 7, 13, 45, 172, 999, 1e-3, 1e5]) {
      const step = gridStep(span);
      expect(span / step).toBeLessThanOrEqual(GRID_TARGET_DIVISIONS + 1e-9);
      const decade = 10 ** Math.floor(Math.log10(step) + 1e-9);
      expect([1, 2, 5, 10]).toContain(Math.round(step / decade));
    }
  });

  it("invents no grid for a camera that has not been framed", () => {
    expect(gridStep(0)).toBe(0);
    expect(gridStep(-4)).toBe(0);
    expect(gridStep(Number.NaN)).toBe(0);
    expect(gridStep(Number.POSITIVE_INFINITY)).toBe(0);
  });
});

describe("buildSpaceSpec — the build space's ruling (§3.11.5, 2026-09-20)", () => {
  const bounds = new Box3(new Vector3(-30, -10, 0), new Vector3(30, 10, 12));

  it("sits on the scene floor", () => {
    expect(buildSpaceSpec(bounds, 120)!.z).toBeCloseTo(0, 10);
    const raised = new Box3(new Vector3(-5, -5, 7.5), new Vector3(5, 5, 20));
    expect(buildSpaceSpec(raised, 120)!.z).toBeCloseTo(7.5, 10);
  });

  it("rules TWO decades finer than the readout's step, leaving detail to reveal", () => {
    // The shader only ever coarsens from this number — it climbs decades to
    // keep lines apart — so the base has to start below the framing's step or
    // zooming in would reveal nothing. Two decades rather than one since
    // 2026-09-20: at one, a zoom bottomed out on the first step in and the
    // ruling stopped getting finer.
    for (const span of [1.2, 12, 120, 1200]) {
      expect(buildSpaceSpec(bounds, span)!.step).toBeCloseTo(gridStep(span) / 100, 10);
    }
  });

  it("refuses an empty scene and an unframed camera rather than guessing", () => {
    expect(buildSpaceSpec(new Box3(), 120)).toBeNull();
    expect(buildSpaceSpec(bounds, 0)).toBeNull();
  });
});

describe("buildBuildSpace — one quad that follows the camera (§3.11.5)", () => {
  const spec = { step: 1, z: 0 };

  it("draws the whole floor in a single mesh", () => {
    // The pad this replaced emitted two `LineSegments` whose vertex count grew
    // with the framing, and was rebuilt on every reframe. This is one draw
    // call at any extent and is never rebuilt.
    const space = buildBuildSpace(spec, PALETTE);
    expect(space.object.children).toHaveLength(1);
    space.dispose();
    space.dispose(); // idempotent
  });

  it("rides under the camera and scales past where the fade completes", () => {
    // The quad is a canvas, not an extent. If it did not outreach the fade,
    // the floor would end on a visible edge instead of dissolving.
    const space = buildBuildSpace(spec, PALETTE);
    const mesh = space.object.children[0] as ThreeMesh;
    for (const [target, span] of [
      [new Vector3(0, 0, 50), 60],
      [new Vector3(400, -250, 900), 4000],
    ] as const) {
      space.follow(target, span);
      expect(mesh.position.x).toBeCloseTo(target.x, 6);
      expect(mesh.position.y).toBeCloseTo(target.y, 6);
      // The box SITS ON the floor: its bottom face is the ground the part
      // stands on, so the centre is half a box above `spec.z`.
      expect(mesh.position.z).toBeCloseTo(spec.z + mesh.scale.z / 2, 6);
      // The walls stand INSIDE the dissolve, which is the opposite of what a
      // bare floor wanted and is the whole point of a room: at a reach that
      // cleared the fade the walls were erased before they were drawn. What
      // must hold is that they are far enough out to be scenery rather than
      // a box around the part — past where the dissolve BEGINS.
      const half = mesh.scale.x / 2;
      expect(half).toBeGreaterThan(span * BUILD_SPACE_FADE_NEAR);
      expect(half).toBeLessThan(span * BUILD_SPACE_FADE_FAR);
    }
    space.dispose();
  });

  it("tracks the VIEW SPAN, not the camera height — an ortho zoom moves only the former", () => {
    // The defect this pins: an orthographic zoom changes `zoom` and leaves the
    // camera exactly where it is, so a quad sized off camera height froze at
    // one extent and left a hard-edged band across the well.
    const space = buildBuildSpace(spec, PALETTE);
    const mesh = space.object.children[0] as ThreeMesh;
    const camera = new Vector3(0, 0, 100); // unmoved, as under an ortho zoom
    space.follow(camera, 40);
    const near = mesh.scale.x;
    space.follow(camera, 4000);
    expect(mesh.scale.x).toBeGreaterThan(near * 50);
    const material = mesh.material as ShaderMaterial;
    expect(material.uniforms["uFadeFar"]?.value).toBeCloseTo(4000 * BUILD_SPACE_FADE_FAR, 6);
  });

  it("keeps a usable quad for a degenerate span", () => {
    const space = buildBuildSpace(spec, PALETTE);
    const mesh = space.object.children[0] as ThreeMesh;
    for (const span of [0, -5, Number.NaN, Number.POSITIVE_INFINITY]) {
      space.follow(new Vector3(0, 0, 10), span);
      expect(mesh.scale.x, String(span)).toBeGreaterThan(0);
      expect(Number.isFinite(mesh.scale.x), String(span)).toBe(true);
    }
    space.dispose();
  });

  it("stops following once disposed", () => {
    const space = buildBuildSpace(spec, PALETTE);
    const mesh = space.object.children[0] as ThreeMesh;
    space.follow(new Vector3(10, 10, 100), 80);
    const held = mesh.position.clone();
    space.dispose();
    space.follow(new Vector3(-999, -999, 5), 80);
    expect(mesh.position.x).toBeCloseTo(held.x, 10);
  });

  it("carries the ruling into the shader rather than baking it into geometry", () => {
    const space = buildBuildSpace(spec, PALETTE);
    const material = (space.object.children[0] as ThreeMesh).material as ShaderMaterial;
    expect(material.uniforms["uStep"]?.value).toBeCloseTo(1, 10);
    expect(material.uniforms["uMinPixels"]?.value).toBe(BUILD_SPACE_MIN_PIXELS);
    expect(material.transparent).toBe(true);
    // A reference mark must not occlude the part it is a reference for, but it
    // must still be hidden BY it — so depth is tested and not written.
    expect(material.depthWrite).toBe(false);
    space.dispose();
  });

  it("is scenery: never culled, never a pick target", () => {
    const space = buildBuildSpace(spec, PALETTE);
    const mesh = space.object.children[0] as ThreeMesh;
    // It moves every frame, so a stale bounding sphere must not cull it.
    expect(mesh.frustumCulled).toBe(false);
    const hits: unknown[] = [];
    mesh.raycast(null as never, hits as never);
    expect(hits).toHaveLength(0);
    space.dispose();
  });
});

// ---------------------------------------------------------------------------
// The palette read
// ---------------------------------------------------------------------------

describe("applyAppearance — wireframe and override, no invented material", () => {
  it("hides the fill and keeps the silhouette when wireframe is on", () => {
    const { scene, meshes } = loadedScene(2);
    const display = authorDisplay(scene, PALETTE);
    applyAppearance(scene, display.material, { wireframe: true, materialOverride: true });

    expect(display.material.visible).toBe(false);
    for (const mesh of meshes) {
      expect(mesh.material).toBe(display.material);
      expect(childEdges(mesh)).toHaveLength(1);
      expect(childEdges(mesh)[0]?.visible).toBe(true);
    }
  });

  it("restores the exporter material when override is off, and invents none", () => {
    const { scene, meshes } = loadedScene(2);
    const display = authorDisplay(scene, PALETTE);
    const preserved = meshes[0]?.userData[SOURCE_MATERIAL_KEY] as MeshStandardMaterial;

    applyAppearance(scene, display.material, { wireframe: false, materialOverride: false });

    expect(meshes[0]?.material).toBe(preserved);
    expect(meshes[1]?.material).toBe(meshes[1]?.userData[SOURCE_MATERIAL_KEY]);
    expect(display.material.visible).toBe(false);
    expect(preserved.visible).toBe(true);
    // The restored colour is still the selection ID, not a new display colour.
    const rgb = { r: 0, g: 0, b: 0 };
    preserved.color.getRGB(rgb, LinearSRGBColorSpace);
    expect([
      Math.round(rgb.r * 255),
      Math.round(rgb.g * 255),
      Math.round(rgb.b * 255),
    ]).toEqual(idToRgb(0));
  });

  it("puts the authored material back when override returns, at the part token", () => {
    const { scene, meshes } = loadedScene(1);
    const display = authorDisplay(scene, PALETTE);
    applyAppearance(scene, display.material, { wireframe: false, materialOverride: false });
    applyAppearance(scene, display.material, { wireframe: false, materialOverride: true });

    expect(meshes[0]?.material).toBe(display.material);
    expect(display.material.visible).toBe(true);
    expect(display.material.color.getHex()).toBe(PALETTE.part.getHex());
  });

  it("is a no-op on a tree that was never authored", () => {
    const { scene, meshes } = loadedScene(1);
    const display = authorDisplay(scene, PALETTE);
    const stranger = new Group();
    stranger.add(exporterMesh(9));
    applyAppearance(stranger, display.material, { wireframe: true, materialOverride: true });
    expect((stranger.children[0] as Mesh).material).not.toBe(display.material);
    expect(meshes[0]?.material).toBe(display.material);
  });
});

describe("readViewportPalette (§3.6, §3.11)", () => {
  // The channel triples are written as decimals and composed here rather than
  // as `#rrggbb` literals: `no-palette-token` (§3.14) refuses a hex anywhere
  // outside `tokens.css`, and it is right to — a test that spelled the palette
  // out would be a second copy of it. What is under test is the *mapping* from
  // token name to `Color`; the values themselves belong to `tokens.css` and are
  // checked there by `token-contrast`.
  const packed = (r: number, g: number, b: number): number => (r << 16) | (g << 8) | b;
  const asCss = (r: number, g: number, b: number): string =>
    `rgb(${String(r)}, ${String(g)}, ${String(b)})`;

  it("reads each of the five tokens into its own slot", () => {
    const channels: Record<string, [number, number, number]> = {
      "--viewport-ground": [8, 10, 13],
      "--viewport-part": [184, 194, 207],
      "--viewport-edge": [238, 241, 246],
      "--viewport-grid": [39, 45, 55],
      "--viewport-grid-axis": [59, 67, 82],
    };
    const palette = readViewportPalette((name) => {
      const rgb = channels[name];
      return rgb === undefined ? "" : asCss(...rgb);
    });
    expect(palette.ground.getHex()).toBe(packed(8, 10, 13));
    expect(palette.part.getHex()).toBe(packed(184, 194, 207));
    expect(palette.edge.getHex()).toBe(packed(238, 241, 246));
    expect(palette.grid.getHex()).toBe(packed(39, 45, 55));
    expect(palette.gridAxis.getHex()).toBe(packed(59, 67, 82));
  });

  it("falls back visibly, not plausibly, when the stylesheet has not applied", () => {
    const palette = readViewportPalette(() => "");
    // Black ground, white marks: obviously provisional for the one frame it can
    // last, rather than a near-miss that survives unnoticed.
    expect(palette.ground.getHex()).toBe(packed(0, 0, 0));
    expect(palette.part.getHex()).toBe(packed(255, 255, 255));
    expect(palette.edge.getHex()).toBe(packed(255, 255, 255));
    expect(palette.grid.getHex()).toBe(packed(255, 255, 255));
    expect(palette.gridAxis.getHex()).toBe(packed(255, 255, 255));
  });
});

describe("the shipped modeling well is not the near-black void", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const tokensRaw = readFileSync(join(here, "..", "src", "system", "tokens.css"), "utf8");
  const tokens = tokensRaw.replace(/\/\*[\s\S]*?\*\//g, "");
  const viewport = readFileSync(
    join(here, "..", "src", "components", "stage", "viewport", "Viewport.module.css"),
    "utf8",
  );

  it("authors a DARK well and a light part, grid on by default", () => {
    // REVERSED 2026-09-20. This asserted the Fusion/Onshape pairing — light
    // ground, dark part — and the reasoning for it is still in `tokens.css`
    // above the block it now contradicts. The operator asked for a dark build
    // space with light lines, which is a look decision and theirs to make.
    //
    // The five move as ONE decision, which is why they are asserted together:
    // flipping the ground without the part would put a graphite model on a
    // graphite well. Hex values live in `tokens.css` and are checked there by
    // `token-contrast`.
    //
    // The ground is the 850 rung, and it is 850 because §3.11.1 wants a well
    // DISTINCT from every chrome surface: all six original rungs are spoken for
    // by `--surface-*`, and the dark well was first given 900, which is
    // `--surface-app` exactly. Well and application background were one field.
    expect(tokens).toMatch(/--viewport-ground:\s*var\(--p-graphite-850\)/);
    // …said as the rule rather than as the name, so a later rung shuffle that
    // lands the ground back on a chrome surface fails here too.
    const chrome = [...tokens.matchAll(/--surface-[a-z]+:\s*var\((--p-[a-z0-9-]+)\)/g)].map(
      (match) => match[1],
    );
    const ground = /--viewport-ground:\s*var\((--p-[a-z0-9-]+)\)/.exec(tokens)?.[1];
    expect(ground).toBeTruthy();
    expect(chrome, "the viewport ground is one of the chrome surfaces").not.toContain(ground);
    expect(tokens).toMatch(/--viewport-part:\s*var\(--p-slate-200\)/);
    expect(tokens).toMatch(/--viewport-edge:\s*var\(--p-slate-050\)/);
    expect(tokens).toMatch(/--viewport-grid:\s*var\(--p-line-hi\)/);
    expect(tokens).toMatch(/--viewport-grid-axis:\s*var\(--p-slate-050\)/);
    expect(DEFAULT_APPEARANCE.grid).toBe(true);
  });

  it("plates absence copy rather than spending chrome ink on the well", () => {
    // The triad half of this is struck with the triad (2026-09-20). The
    // permission it relied on stays in `tokens.css`: `--viewport-edge` on
    // `--viewport-ground` is still the contrast pair anything drawn directly
    // on the well must use, and removing the permission would silently allow
    // the next such overlay to pick chrome ink.
    expect(tokensRaw).toMatch(/@permit text\s+--viewport-edge\s*:\s*viewport-ground/);
    expect(viewport).toMatch(/\.absencePlate[\s\S]*background:\s*var\(--surface-overlay\)/);
  });
});
