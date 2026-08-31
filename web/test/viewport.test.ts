// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The viewport's non-pixel half (INTERFACE.md §5.1, §5.2, §5.3, §5.4, §5.5).
//
// Everything asserted here is a *contract*, not an appearance: what may be read
// out of the server's GLB, the exact client explode formula, the camera
// vocabulary the URL and `heph render` share, the section half-space's agreement
// with the server's cut, and the scene-graph operations §1 hands the client.
// None of it needs a GPU, which is why `viewport/engine.ts` — the one module
// that does — holds no logic of its own.

import { describe, expect, it } from "vitest";
import { Box3, Group, Mesh, PerspectiveCamera, Vector3 } from "three";
import type { Object3D } from "three";
import type { GLTF } from "three/addons/loaders/GLTFLoader.js";
import { GlbFormatError, readGlbGeometry } from "../src/viewport/glb";
import { explodeTranslation } from "../src/viewport/explode";
import {
  ISO_ELEVATION_DEG,
  VIEW_ANGLES,
  anglesFromDirection,
  eyeDirection,
  nameForDirection,
  upHint,
  viewAngles,
} from "../src/viewport/cameras";
import {
  clippingHalfSpace,
  formatSectionPlane,
  parseSectionPlane,
  retains,
} from "../src/viewport/section";
import {
  applyExplode,
  applyPerspectiveFraming,
  applyVisibility,
  boundsAt,
  framingFor,
  perspectiveFovDeg,
  indexSolidNodes,
  solidCentroids,
} from "../src/viewport/scene";
import { snapshotSolids } from "../src/viewport/testHook";
import { STANDARD_VIEWS } from "../src/state/workspace";
import { fakeGlb } from "./glb";

// ---------------------------------------------------------------------------
// §5.1 — what the client may read out of the GLB, and what it may not
// ---------------------------------------------------------------------------

describe("readGlbGeometry (§5.1)", () => {
  it("reads solid_index, label and explode_offset per mesh", () => {
    const geometry = readGlbGeometry(
      fakeGlb({
        solids: [
          { solid_index: 0, label: "base", explode_offset: [1, 0, -2], primitives: 3 },
          { solid_index: 1, label: "tread", explode_offset: [0.5, 0.25, 0] },
        ],
      }),
    );
    expect(geometry.mesh_count).toBe(2);
    expect(geometry.solids[0]).toEqual({
      mesh_index: 0,
      solid_index: 0,
      label: "base",
      explode_offset: [1, 0, -2],
      primitive_count: 3,
    });
    expect(geometry.solids[1]?.label).toBe("tread");
  });

  it("returns a null label rather than inventing one", () => {
    const geometry = readGlbGeometry(fakeGlb({ solids: [{ solid_index: 4 }] }));
    expect(geometry.solids[0]?.label).toBeNull();
    expect(geometry.solids[0]?.solid_index).toBe(4);
  });

  it("exposes no selection id and no bundle link — those are server values (§1, §12.3)", () => {
    const geometry = readGlbGeometry(fakeGlb({ solids: [{ solid_index: 0, label: "a" }] }));
    const serialized = JSON.stringify(geometry);
    expect(serialized).not.toContain("selection_id");
    expect(serialized).not.toContain("selection_bundle_ref");
    expect(serialized).not.toContain("artifact:build");
    expect(Object.keys(geometry.solids[0] as object).sort()).toEqual([
      "explode_offset",
      "label",
      "mesh_index",
      "primitive_count",
      "solid_index",
    ]);
  });

  it("refuses a mesh with no explode_offset instead of exploding it by zero (§1)", () => {
    expect(() => readGlbGeometry(fakeGlb({ solids: [{ solid_index: 0, withoutOffset: true }] })))
      .toThrow(GlbFormatError);
  });

  it("refuses a non-float3 explode_offset", () => {
    expect(() =>
      readGlbGeometry(fakeGlb({ solids: [{ solid_index: 0, explode_offset: [1, 2] }] })),
    ).toThrow(/float3/);
    expect(() =>
      readGlbGeometry(fakeGlb({ solids: [{ solid_index: 0, explode_offset: [1, 2, "x"] }] })),
    ).toThrow(/non-finite/);
  });

  it("refuses a mesh with no extras at all", () => {
    expect(() => readGlbGeometry(fakeGlb({ solids: [{ solid_index: 0, withoutExtras: true }] })))
      .toThrow(/no extras/);
  });

  it("refuses bytes that are not a GLB container", () => {
    expect(() => readGlbGeometry(new Uint8Array([1, 2, 3, 4]).buffer)).toThrow(GlbFormatError);
    const wrongMagic = new ArrayBuffer(24);
    expect(() => readGlbGeometry(wrongMagic)).toThrow(/not a GLB/);
  });
});

// ---------------------------------------------------------------------------
// §5.2 / §1 — `offset · t`, and nothing else
// ---------------------------------------------------------------------------

describe("explodeTranslation (§5.2)", () => {
  const offset = [3, -1.5, 0.25] as const;

  it("is exactly offset · t", () => {
    expect(explodeTranslation(offset, 1)).toEqual([3, -1.5, 0.25]);
    expect(explodeTranslation(offset, 0.5)).toEqual([1.5, -0.75, 0.125]);
    expect(explodeTranslation(offset, 0.2)).toEqual([3 * 0.2, -1.5 * 0.2, 0.25 * 0.2]);
  });

  it("mirrors the server's t<=0 short-circuit, including the sign of zero", () => {
    // `_explode_offset` returns `+0.0` for t <= 0; a plain multiplication would
    // give `-0` on the negative component. Same displacement, different bytes —
    // and the server-side byte-equivalence test excludes t = 0 for exactly this
    // reason, so the client closes it rather than inheriting the exclusion.
    const zero = explodeTranslation(offset, 0);
    expect(zero).toEqual([0, 0, 0]);
    expect(Object.is(zero[1], -0)).toBe(false);
    expect(Object.is(zero[1], 0)).toBe(true);
    expect(explodeTranslation(offset, -1)).toEqual([0, 0, 0]);
  });

  it("treats a non-finite t as no displacement rather than NaN geometry", () => {
    expect(explodeTranslation(offset, Number.NaN)).toEqual([0, 0, 0]);
  });
});

// ---------------------------------------------------------------------------
// §5.5 — the camera vocabulary shared with `core/render/cameras.py`
// ---------------------------------------------------------------------------

describe("cameras (§5.5)", () => {
  it("declares exactly the eight names the workspace vocabulary carries", () => {
    expect(Object.keys(VIEW_ANGLES).sort()).toEqual([...STANDARD_VIEWS].sort());
  });

  it("mirrors `cameras.py::STANDARD_VIEWS` angle for angle", () => {
    // Transcribed from `core/render/cameras.py`:47-56. A change on either side
    // must break this, which is the only mechanical tie between the two files.
    expect(VIEW_ANGLES["+X"]).toEqual({ azimuth_deg: 0, elevation_deg: 0 });
    expect(VIEW_ANGLES["-X"]).toEqual({ azimuth_deg: 180, elevation_deg: 0 });
    expect(VIEW_ANGLES["+Y"]).toEqual({ azimuth_deg: 90, elevation_deg: 0 });
    expect(VIEW_ANGLES["-Y"]).toEqual({ azimuth_deg: 270, elevation_deg: 0 });
    expect(VIEW_ANGLES["+Z"]).toEqual({ azimuth_deg: 0, elevation_deg: 90 });
    expect(VIEW_ANGLES["-Z"]).toEqual({ azimuth_deg: 0, elevation_deg: -90 });
    expect(VIEW_ANGLES["front"]).toEqual({ azimuth_deg: 270, elevation_deg: 0 });
    expect(VIEW_ANGLES["iso"].azimuth_deg).toBe(45);
    expect(ISO_ELEVATION_DEG).toBeCloseTo(35.264389682754654, 12);
  });

  it("reproduces `ViewSpec.eye_direction` in a Z-up frame", () => {
    expect(eyeDirection(VIEW_ANGLES["+X"])[0]).toBeCloseTo(1, 12);
    expect(eyeDirection(VIEW_ANGLES["+Z"])[2]).toBeCloseTo(1, 12);
    expect(eyeDirection(VIEW_ANGLES["-Z"])[2]).toBeCloseTo(-1, 12);
    expect(eyeDirection(VIEW_ANGLES["+Y"])[1]).toBeCloseTo(1, 12);
  });

  it("uses +Y as the up hint only where the view axis is (anti)parallel to +Z", () => {
    expect(upHint(eyeDirection(VIEW_ANGLES["+Z"]))).toEqual([0, 1, 0]);
    expect(upHint(eyeDirection(VIEW_ANGLES["-Z"]))).toEqual([0, 1, 0]);
    expect(upHint(eyeDirection(VIEW_ANGLES["iso"]))).toEqual([0, 0, 1]);
  });

  it("parses the az/el grammar and refuses anything outside it", () => {
    expect(viewAngles("az45_el30")).toEqual({ azimuth_deg: 45, elevation_deg: 30 });
    expect(viewAngles("az-12.5_el-3")).toEqual({ azimuth_deg: -12.5, elevation_deg: -3 });
    expect(viewAngles("sideways")).toBeNull();
    expect(viewAngles("az45")).toBeNull();
  });

  it("snapshots a free orbit to a name the renderer can reproduce", () => {
    const direction = eyeDirection({ azimuth_deg: 31.4, elevation_deg: 12.2 });
    expect(nameForDirection(direction)).toBe("az31_el12");
    // Round-tripping the name lands on (approximately) the same camera.
    const angles = viewAngles("az31_el12");
    expect(angles).not.toBeNull();
    expect(anglesFromDirection(eyeDirection(angles!)).azimuth_deg).toBeCloseTo(31, 6);
  });

  it("returns the standard name when an orbit lands on a standard camera", () => {
    expect(nameForDirection(eyeDirection(VIEW_ANGLES["iso"]))).toBe("iso");
    expect(nameForDirection(eyeDirection(VIEW_ANGLES["+X"]))).toBe("+X");
    // `-Y` and `front` are the same angles in `cameras.py`; the first in
    // vocabulary order wins, deterministically.
    expect(nameForDirection(eyeDirection(VIEW_ANGLES["front"]))).toBe("-Y");
  });
});

// ---------------------------------------------------------------------------
// §5.3 — the preview's half-space agrees with the server's cut
// ---------------------------------------------------------------------------

describe("section (§5.3)", () => {
  it("parses and round-trips the workspace spelling", () => {
    expect(parseSectionPlane("+Z@12.5")).toEqual({
      axis: "Z",
      sign: 1,
      offset: 12.5,
      spec: "+Z@12.5",
    });
    expect(parseSectionPlane("-X@-3")?.sign).toBe(-1);
    expect(formatSectionPlane(1, "Y", 30)).toBe("+Y@30");
    expect(formatSectionPlane(-1, "Y", 30.00004)).toBe("-Y@30");
  });

  it("refuses the spellings §4.5's URL codec does not carry", () => {
    // The server's parser accepts these; the URL codec does not, deliberately —
    // `c` means a different plane for a different build.
    expect(parseSectionPlane("+Z@c")).toBeNull();
    expect(parseSectionPlane("Z@0")).toBeNull();
    expect(parseSectionPlane("+z@0")).toBeNull();
  });

  it("keeps the half the server keeps: sign·(coord − offset) <= 0", () => {
    const plane = parseSectionPlane("+Z@10");
    expect(plane).not.toBeNull();
    const half = clippingHalfSpace(plane!);
    // three.js keeps `n · p + c >= 0`; check the two agree pointwise.
    for (const z of [-5, 0, 9.9, 10, 10.1, 40]) {
      const point: readonly [number, number, number] = [0, 0, z];
      const threeKeeps =
        half.normal[0] * point[0] +
          half.normal[1] * point[1] +
          half.normal[2] * point[2] +
          half.constant >=
        0;
      expect(threeKeeps).toBe(retains(plane!, point));
    }
    // `+Z@…` cuts away the +Z half (`channels.py::parse_section_plane`).
    expect(retains(plane!, [0, 0, 20])).toBe(false);
    expect(retains(plane!, [0, 0, 0])).toBe(true);
  });

  it("inverts with the sign", () => {
    const plane = parseSectionPlane("-Z@10");
    expect(retains(plane!, [0, 0, 20])).toBe(true);
    expect(retains(plane!, [0, 0, 0])).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// §5.2 / §5.4 — the scene-graph operations
// ---------------------------------------------------------------------------

/** A loaded-GLTF stand-in: real `Object3D`s, and the loader's own association map. */
function fakeGltf(labels: readonly (string | null)[]): {
  gltf: GLTF;
  objects: Object3D[];
} {
  const scene = new Group();
  const associations = new Map<Object3D, { meshes: number; primitives?: number }>();
  const objects: Object3D[] = [];
  labels.forEach((_label, meshIndex) => {
    const mesh = new Mesh();
    // A 2×2×2 cube's worth of extent, so bounding boxes are not degenerate.
    mesh.geometry.boundingBox = new Box3(new Vector3(-1, -1, -1), new Vector3(1, 1, 1));
    mesh.geometry.computeBoundingBox = () => undefined;
    scene.add(mesh);
    associations.set(mesh, { meshes: meshIndex, primitives: 0 });
    objects.push(mesh);
  });
  return {
    gltf: { scene, parser: { associations } } as unknown as GLTF,
    objects,
  };
}

function geometryFor(labels: readonly (string | null)[], offsets: readonly (readonly number[])[]) {
  return readGlbGeometry(
    fakeGlb({
      solids: labels.map((label, i) => ({
        solid_index: i,
        ...(label === null ? {} : { label }),
        explode_offset: offsets[i] as readonly [number, number, number],
      })),
    }),
  );
}

describe("scene (§5.2, §5.4)", () => {
  it("joins meshes to nodes through the loader's associations, not by position", () => {
    const { gltf, objects } = fakeGltf(["a", "b"]);
    // Reverse the scene children: a position-based join would now be wrong.
    gltf.scene.children.reverse();
    const geometry = geometryFor(["a", "b"], [[1, 0, 0], [0, 2, 0]]);
    const index = indexSolidNodes(gltf, geometry);
    expect(index.byMesh.get(0)?.object).toBe(objects[0]);
    expect(index.byMesh.get(1)?.object).toBe(objects[1]);
    expect(index.bySolid.get(1)?.solid.label).toBe("b");
  });

  it("translates each node by explode_offset · t and re-frames nothing", () => {
    const { gltf, objects } = fakeGltf(["a", "b"]);
    const geometry = geometryFor(["a", "b"], [[4, 0, 0], [-2, 6, 0]]);
    const index = indexSolidNodes(gltf, geometry);

    applyExplode(index, 0.5);
    expect(objects[0]?.position.toArray()).toEqual([2, 0, 0]);
    expect(objects[1]?.position.toArray()).toEqual([-1, 3, 0]);

    applyExplode(index, 0);
    expect(objects[0]?.position.toArray()).toEqual([0, 0, 0]);
  });

  it("increases every pairwise centroid distance as t rises (G4.6's shape)", () => {
    const { gltf } = fakeGltf(["a", "b", "c"]);
    const geometry = geometryFor(["a", "b", "c"], [[3, 0, 0], [-3, 0, 0], [0, 5, 0]]);
    const index = indexSolidNodes(gltf, geometry);

    const distancesAt = (t: number): number[] => {
      applyExplode(index, t);
      const centroids = [...solidCentroids(index).entries()].sort((x, y) => x[0] - y[0]);
      const out: number[] = [];
      for (let i = 0; i < centroids.length; i += 1) {
        for (let j = i + 1; j < centroids.length; j += 1) {
          const a = centroids[i]?.[1] as [number, number, number];
          const b = centroids[j]?.[1] as [number, number, number];
          out.push(Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]));
        }
      }
      return out;
    };

    const collapsed = distancesAt(0);
    const exploded = distancesAt(1);
    expect(exploded).toHaveLength(3);
    exploded.forEach((distance, i) => {
      expect(distance).toBeGreaterThan(collapsed[i] as number);
    });
  });

  it("hides the meshes of a hidden geometry-entry label, and only those", () => {
    const { gltf, objects } = fakeGltf(["base", "tread", "tread"]);
    const geometry = geometryFor(["base", "tread", "tread"], [[1, 0, 0], [0, 1, 0], [0, 0, 1]]);
    const index = indexSolidNodes(gltf, geometry);

    applyVisibility(index, new Set(["tread"]));
    expect(objects[0]?.visible).toBe(true);
    expect(objects[1]?.visible).toBe(false);
    expect(objects[2]?.visible).toBe(false);

    applyVisibility(index, new Set());
    expect(objects[1]?.visible).toBe(true);
  });

  it("never hides an unlabelled mesh: no row could have asked for it", () => {
    const { gltf, objects } = fakeGltf([null]);
    const index = indexSolidNodes(gltf, geometryFor([null], [[0, 0, 0]]));
    applyVisibility(index, new Set(["anything"]));
    expect(objects[0]?.visible).toBe(true);
  });

  it("frames the plain bbox at t = 0 — the camera `mask`/`rgb`/`section` use", () => {
    // `channels.py::_framing` frames every channel but `explode` to the plain
    // scene bbox, and G4.5 screenshots the viewport "at the pass's own …
    // camera". Two 2-unit cubes at the origin span [-1, 1].
    const { gltf } = fakeGltf(["a", "b"]);
    const index = indexSolidNodes(gltf, geometryFor(["a", "b"], [[10, 0, 0], [-10, 0, 0]]));
    const bounds = boundsAt(index, 0);
    expect(bounds.min.x).toBeCloseTo(-1, 6);
    expect(bounds.max.x).toBeCloseTo(1, 6);
  });

  it("frames the t = 1 extent once explode is engaged — the `explode` camera", () => {
    const { gltf } = fakeGltf(["a", "b"]);
    const index = indexSolidNodes(gltf, geometryFor(["a", "b"], [[10, 0, 0], [-10, 0, 0]]));
    // The answer does not depend on where the slider currently is.
    applyExplode(index, 0.3);
    const bounds = boundsAt(index, 1);
    expect(bounds.min.x).toBeCloseTo(-11, 6);
    expect(bounds.max.x).toBeCloseTo(11, 6);
  });

  it("produces a framing whose extents match the viewport aspect", () => {
    const bounds = new Box3(new Vector3(-5, -5, -5), new Vector3(5, 5, 5));
    const framing = framingFor(bounds, "iso", 2);
    expect(framing).not.toBeNull();
    expect(framing!.halfWidth / framing!.halfHeight).toBeCloseTo(2, 6);
    expect(framing!.near).toBeGreaterThan(0);
    expect(framing!.far).toBeGreaterThan(framing!.near);
  });

  it("returns no framing for a view outside the vocabulary", () => {
    const bounds = new Box3(new Vector3(0, 0, 0), new Vector3(1, 1, 1));
    expect(framingFor(bounds, "sideways", 1)).toBeNull();
  });

  it("derives a perspective FOV from the same half-height the ortho camera uses", () => {
    // A 50-unit half-height at 100 units of distance is 2*atan(0.5) degrees.
    expect(perspectiveFovDeg(50, 100)).toBeCloseTo((2 * Math.atan(0.5) * 180) / Math.PI, 10);
    expect(perspectiveFovDeg(0, 100)).toBe(0);
    expect(perspectiveFovDeg(10, 0)).toBe(0);
    expect(perspectiveFovDeg(Number.NaN, 10)).toBe(0);
  });

  it("places a perspective camera on the same eye/target as the ortho framing", () => {
    const bounds = new Box3(new Vector3(-5, -5, -5), new Vector3(5, 5, 5));
    const framing = framingFor(bounds, "iso", 1);
    expect(framing).not.toBeNull();
    if (framing === null) return;
    const camera = new PerspectiveCamera();
    applyPerspectiveFraming(camera, framing);
    expect(camera.position.toArray()).toEqual([...framing.eye]);
    const distance = Math.hypot(
      framing.eye[0] - framing.target[0],
      framing.eye[1] - framing.target[1],
      framing.eye[2] - framing.target[2],
    );
    expect(camera.fov).toBeCloseTo(perspectiveFovDeg(framing.halfHeight, distance), 10);
    expect(camera.aspect).toBeCloseTo(framing.halfWidth / framing.halfHeight, 10);
  });
});

// ---------------------------------------------------------------------------
// The harness handle (§5.2, G4.6)
// ---------------------------------------------------------------------------

describe("snapshotSolids", () => {
  it("reports positions and centroids as plain JSON, and never a distance", () => {
    const { gltf } = fakeGltf(["a", "b"]);
    const index = indexSolidNodes(gltf, geometryFor(["a", "b"], [[2, 0, 0], [0, -4, 0]]));
    applyExplode(index, 1);
    const snapshot = snapshotSolids(index);
    expect(snapshot).toHaveLength(2);
    expect(snapshot[0]?.position).toEqual([2, 0, 0]);
    expect(snapshot[0]?.explode_offset).toEqual([2, 0, 0]);
    expect(snapshot[0]?.centroid?.[0]).toBeCloseTo(2, 6);
    expect(snapshot[1]?.label).toBe("b");
    expect(JSON.stringify(snapshot)).not.toContain("distance");
  });

  it("is empty before a GLB is loaded rather than throwing", () => {
    expect(snapshotSolids(null)).toEqual([]);
  });
});
