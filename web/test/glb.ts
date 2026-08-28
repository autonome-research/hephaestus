// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// A minimal GLB **writer** for the viewport tests.
//
// `core/render/gltf.py::export_gltf` is the only real producer, and it needs
// OCCT, a tessellation and a selection catalog — none of which a vitest run has.
// So the shape of its output is transcribed here (one mesh per solid, one
// primitive per face, `extras` on both, `asset.extras` carrying the three refs)
// and written into a real GLB container, chunk lengths and padding included.
//
// It is the *container* the tests need to be real: `readGlbGeometry` parses the
// binary header and walks chunks, and a fixture that handed it a bare JSON
// object would test nothing about that half.

export interface FakeSolid {
  readonly solid_index: number;
  readonly label?: string;
  readonly explode_offset?: readonly [number, number, number] | unknown;
  readonly primitives?: number;
  /** Omit `extras.explode_offset` entirely — the malformed case §5.1 refuses. */
  readonly withoutOffset?: boolean;
  /** Omit `extras` entirely. */
  readonly withoutExtras?: boolean;
}

export interface FakeGlbOptions {
  readonly solids: readonly FakeSolid[];
  readonly bundleRef?: string;
  readonly sourceRef?: string;
  readonly tableRef?: string;
}

function meshJson(solid: FakeSolid): Record<string, unknown> {
  const primitives = Array.from({ length: solid.primitives ?? 1 }, (_unused, face) => ({
    attributes: { POSITION: 0 },
    indices: 1,
    mode: 4,
    extras: { selection_id: 1000 + face, kind: "face", solid_index: solid.solid_index, face_index: face },
  }));
  if (solid.withoutExtras === true) return { primitives };
  const extras: Record<string, unknown> = {
    selection_id: solid.solid_index + 1,
    kind: "solid",
    solid_index: solid.solid_index,
  };
  if (solid.withoutOffset !== true) {
    extras["explode_offset"] = solid.explode_offset ?? [1, 2, 3];
  }
  if (solid.label !== undefined) extras["label"] = solid.label;
  return { primitives, extras, name: solid.label ?? `solid_${solid.solid_index}` };
}

/** Write a GLB container whose JSON chunk describes `options.solids`. */
export function fakeGlb(options: FakeGlbOptions): ArrayBuffer {
  const document = {
    asset: {
      version: "2.0",
      generator: "test",
      extras: {
        selection_bundle_ref: options.bundleRef ?? "artifact:selection-bundle:sha256:b",
        source_artifact_ref: options.sourceRef ?? "artifact:build:sha256:a",
        selection_table_ref: options.tableRef ?? "artifact:selection-table:sha256:t",
      },
    },
    scene: 0,
    scenes: [{ nodes: options.solids.map((_unused, i) => i) }],
    nodes: options.solids.map((_unused, i) => ({ mesh: i })),
    meshes: options.solids.map(meshJson),
  };

  const json = new TextEncoder().encode(JSON.stringify(document));
  const padded = (json.length + 3) & ~3;
  const chunk = new Uint8Array(padded);
  chunk.set(json);
  chunk.fill(0x20, json.length); // JSON chunks pad with spaces

  const total = 12 + 8 + padded;
  const buffer = new ArrayBuffer(total);
  const view = new DataView(buffer);
  view.setUint32(0, 0x46546c67, true); // "glTF"
  view.setUint32(4, 2, true);
  view.setUint32(8, total, true);
  view.setUint32(12, padded, true);
  view.setUint32(16, 0x4e4f534a, true); // "JSON"
  new Uint8Array(buffer).set(chunk, 20);
  return buffer;
}
