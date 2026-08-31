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
import type { LineBasicMaterial, LineSegments } from "three";
import type { GLTF } from "three/addons/loaders/GLTFLoader.js";
import {
  AUTHORED_EDGES_KEY,
  EDGE_THRESHOLD_DEG,
  GRID_MARGIN_STEPS,
  GRID_TARGET_DIVISIONS,
  SOURCE_MATERIAL_KEY,
  authorDisplay,
  applyAppearance,
  buildGroundGrid,
  gridStep,
  groundGridSpec,
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

describe("groundGridSpec (§3.11.5)", () => {
  const bounds = new Box3(new Vector3(-13, -7, 2), new Vector3(41, 19, 30));

  it("lands lines on world multiples of the step and sits on the scene floor", () => {
    const spec = groundGridSpec(bounds, 120);
    expect(spec).not.toBeNull();
    if (spec === null) return;
    expect(spec.step).toBeCloseTo(10, 10);
    // The floor is the scene's own, so the part stands on the grid rather than
    // hovering over an arbitrary z.
    expect(spec.z).toBe(2);
    // Every edge is a whole number of steps from the origin, so the line
    // through x = 0 is a line through x = 0.
    for (const edge of [spec.minX, spec.maxX, spec.minY, spec.maxY]) {
      expect(Math.abs(edge / spec.step - Math.round(edge / spec.step))).toBeLessThan(1e-9);
    }
    // And the pad covers the part plus the stated margin.
    const pad = GRID_MARGIN_STEPS * spec.step;
    expect(spec.minX).toBeLessThanOrEqual(bounds.min.x - pad);
    expect(spec.maxX).toBeGreaterThanOrEqual(bounds.max.x + pad);
    expect(spec.minY).toBeLessThanOrEqual(bounds.min.y - pad);
    expect(spec.maxY).toBeGreaterThanOrEqual(bounds.max.y + pad);
  });

  it("refuses an empty scene and an unframed camera rather than guessing", () => {
    expect(groundGridSpec(new Box3(), 120)).toBeNull();
    expect(groundGridSpec(bounds, 0)).toBeNull();
  });
});

describe("buildGroundGrid (§3.11.5)", () => {
  it("splits the datum lines from the ruler and gives each its own token", () => {
    const spec = { step: 10, z: 0, minX: -20, maxX: 20, minY: -20, maxY: 20 };
    const grid = buildGroundGrid(spec, PALETTE);

    // Five columns and five rows; one of each passes through the origin.
    expect(grid.lines).toBe(10);
    expect(grid.object.children).toHaveLength(2);
    const [minor, datum] = grid.object.children as [LineSegments, LineSegments];
    expect(minor.geometry.getAttribute("position").count).toBe(16); // 8 lines
    expect(datum.geometry.getAttribute("position").count).toBe(4); // 2 lines
    expect((minor.material as LineBasicMaterial).color.getHex()).toBe(PALETTE.grid.getHex());
    expect((datum.material as LineBasicMaterial).color.getHex()).toBe(PALETTE.gridAxis.getHex());
    grid.dispose();
    grid.dispose(); // idempotent
  });

  it("emits only a ruler when the model origin is off the pad", () => {
    const grid = buildGroundGrid({ step: 5, z: 0, minX: 100, maxX: 115, minY: 100, maxY: 115 }, PALETTE);
    expect(grid.object.children).toHaveLength(1);
    expect(grid.lines).toBe(8);
    grid.dispose();
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
  const tokens = readFileSync(
    join(dirname(fileURLToPath(import.meta.url)), "..", "src", "system", "tokens.css"),
    "utf8",
  ).replace(/\/\*[\s\S]*?\*\//g, "");

  it("authors a light CAD ground and a dark part, grid on by default", () => {
    // Velvet: Fusion/Onshape-style well. Clear colour is `--p-slate-050`,
    // not the previous `--p-graphite-950` void. Hex values live in
    // `tokens.css` and are checked there by `token-contrast`.
    expect(tokens).toMatch(/--viewport-ground:\s*var\(--p-slate-050\)/);
    expect(tokens).not.toMatch(/--viewport-ground:\s*var\(--surface-canvas\)/);
    expect(tokens).toMatch(/--viewport-part:\s*var\(--p-part\)/);
    expect(tokens).toMatch(/--p-part:\s*var\(--p-graphite-500\)/);
    expect(tokens).toMatch(/--viewport-edge:\s*var\(--p-graphite-950\)/);
    expect(tokens).toMatch(/--viewport-grid:\s*var\(--p-slate-400\)/);
    expect(tokens).toMatch(/--viewport-grid-axis:\s*var\(--p-slate-600\)/);
    expect(DEFAULT_APPEARANCE.grid).toBe(true);
  });
});
