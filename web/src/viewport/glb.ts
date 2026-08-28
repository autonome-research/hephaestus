// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Reading the server's GLB document (INTERFACE.md §5.1).
//
// `GET /artifacts/{ref}/gltf` returns "one **mesh per solid** (mesh count equals
// solid count — a G1 assertion), one **primitive per face** inside its solid's
// mesh, `extras` carrying selection IDs and descriptors". This module reads the
// JSON chunk of that container and returns **exactly three** per-mesh values:
//
//   solid_index      the server's own index for the solid this mesh is
//   label            the server's geometry-tree label for it, or null
//   explode_offset   the float3 displacement at t = 1 (§5.1)
//
// WHAT IT DELIBERATELY DOES NOT READ, and why each omission is load-bearing:
//
// * **`extras.selection_id`.** §12.3: "The browser's raycast therefore supplies
//   `(mesh_index, primitive_index)` as a **hint about which triangle was hit** —
//   never a `selection_id`, and never an authorization." A client that had the
//   ID in hand would eventually submit it, and §1's closed list makes selection
//   IDs server values. So the ID is not parsed, not stored, and not reachable
//   from anything this module returns.
// * **`asset.extras.selection_bundle_ref`** (and the source/table refs beside
//   it). Reading those would be "the client reading a selection link out of a
//   blob", which is why `server/http/geometry.py` publishes them as the
//   `X-Hephaestus-Selection-Bundle` / `X-Hephaestus-Source-Artifact` response
//   headers instead. `useGlb.ts` takes them from the headers; this module never
//   looks inside `asset`.
//
// A mesh with no `explode_offset` is a **malformed document**, not a mesh that
// explodes by zero: §1 forbids the client deriving one, so there is no legal
// fallback and the only honest answer is a refusal. `core/render/gltf.py`'s
// `validate_gltf` refuses to publish such a GLB for the same reason, so the two
// ends agree about what a well-formed document is.

/** A GLB this client cannot read as the document §5.1 describes. */
export class GlbFormatError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "GlbFormatError";
  }
}

/** One mesh of the GLB: one solid of the build (§5.1's mesh-per-solid rule). */
export interface GlbSolid {
  /** Index into `meshes[]` — the raycast hint's `mesh_index` (§12.3). */
  readonly mesh_index: number;
  /** The server's solid index, from `extras.solid_index`. */
  readonly solid_index: number;
  /** The server's geometry-tree label, from `extras.label`; absent ⇒ null. */
  readonly label: string | null;
  /** `extras.explode_offset`: the float3 displacement at `t = 1` (§5.1). */
  readonly explode_offset: readonly [number, number, number];
  /** How many primitives (faces) this mesh carries. A structural fact only. */
  readonly primitive_count: number;
}

/** The whole readable surface of one GLB, in mesh order. */
export interface GlbGeometry {
  readonly solids: readonly GlbSolid[];
  /** `meshes.length`. Equal to the build's solid count by §5.1's construction. */
  readonly mesh_count: number;
}

const GLB_MAGIC = 0x46546c67; // "glTF"
const CHUNK_JSON = 0x4e4f534a; // "JSON"
const GLB_HEADER_BYTES = 12;
const CHUNK_HEADER_BYTES = 8;

/** The JSON chunk of a GLB container, as text. */
function glbJsonChunk(bytes: ArrayBuffer): string {
  if (bytes.byteLength < GLB_HEADER_BYTES) {
    throw new GlbFormatError(`GLB is ${bytes.byteLength} bytes, shorter than its 12-byte header`);
  }
  const view = new DataView(bytes);
  const magic = view.getUint32(0, true);
  if (magic !== GLB_MAGIC) {
    throw new GlbFormatError(`not a GLB: magic 0x${magic.toString(16)} is not 'glTF'`);
  }
  const version = view.getUint32(4, true);
  if (version !== 2) {
    throw new GlbFormatError(`GLB container version ${version} is not 2`);
  }
  const declared = view.getUint32(8, true);
  if (declared > bytes.byteLength) {
    throw new GlbFormatError(
      `GLB declares ${declared} bytes but only ${bytes.byteLength} arrived`,
    );
  }

  // The spec puts the JSON chunk first, but the container permits a scan and a
  // scan costs nothing: walk chunks until the JSON one, rather than asserting a
  // layout this client did not write.
  let offset = GLB_HEADER_BYTES;
  while (offset + CHUNK_HEADER_BYTES <= declared) {
    const length = view.getUint32(offset, true);
    const kind = view.getUint32(offset + 4, true);
    const start = offset + CHUNK_HEADER_BYTES;
    if (start + length > declared) {
      throw new GlbFormatError(`GLB chunk at byte ${offset} runs past the container`);
    }
    if (kind === CHUNK_JSON) {
      return new TextDecoder().decode(new Uint8Array(bytes, start, length));
    }
    offset = start + length;
  }
  throw new GlbFormatError("GLB carries no JSON chunk");
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** `extras.explode_offset` as a float3, or a named refusal. */
function readExplodeOffset(extras: Record<string, unknown>, at: number): [number, number, number] {
  const raw = extras["explode_offset"];
  if (!Array.isArray(raw) || raw.length !== 3) {
    throw new GlbFormatError(
      `mesh ${at} carries no float3 extras.explode_offset; the client may not derive one ` +
        "(INTERFACE.md §1, §5.1)",
    );
  }
  const out: number[] = [];
  for (const component of raw as readonly unknown[]) {
    if (typeof component !== "number" || !Number.isFinite(component)) {
      throw new GlbFormatError(`mesh ${at} has a non-finite component in extras.explode_offset`);
    }
    out.push(component);
  }
  return [out[0] as number, out[1] as number, out[2] as number];
}

/**
 * Read the per-solid document out of GLB `bytes`.
 *
 * Pure and synchronous: no WebGL, no three.js, no network — which is what makes
 * §5.1's contract unit-testable without a browser.
 */
export function readGlbGeometry(bytes: ArrayBuffer): GlbGeometry {
  let document: unknown;
  try {
    document = JSON.parse(glbJsonChunk(bytes)) as unknown;
  } catch (error) {
    if (error instanceof GlbFormatError) throw error;
    throw new GlbFormatError(`GLB JSON chunk is not JSON: ${String(error)}`);
  }
  const root = asRecord(document);
  if (root === null) throw new GlbFormatError("GLB JSON chunk is not an object");
  const meshes = root["meshes"];
  if (!Array.isArray(meshes)) throw new GlbFormatError("GLB declares no meshes");

  const solids: GlbSolid[] = [];
  meshes.forEach((entry: unknown, mesh_index: number) => {
    const mesh = asRecord(entry);
    if (mesh === null) throw new GlbFormatError(`mesh ${mesh_index} is not an object`);
    const extras = asRecord(mesh["extras"]);
    if (extras === null) {
      throw new GlbFormatError(`mesh ${mesh_index} carries no extras`);
    }
    const solidIndex = extras["solid_index"];
    if (typeof solidIndex !== "number" || !Number.isInteger(solidIndex)) {
      throw new GlbFormatError(`mesh ${mesh_index} carries no integer extras.solid_index`);
    }
    const label = extras["label"];
    const primitives = mesh["primitives"];
    solids.push({
      mesh_index,
      solid_index: solidIndex,
      label: typeof label === "string" ? label : null,
      explode_offset: readExplodeOffset(extras, mesh_index),
      primitive_count: Array.isArray(primitives) ? primitives.length : 0,
    });
  });

  return { solids, mesh_count: solids.length };
}
