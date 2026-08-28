// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `GET /artifacts/{ref}/gltf` as a query (INTERFACE.md §5.1, §2.6).
//
// §5.1: "The viewport loads `GET /artifacts/{ref}/gltf` for the **pinned**
// build." The pinned one — `artifact_ref` from workspace state, never "the
// current build", because §4.5 makes the pin sticky and §12.1 makes every
// inspection carry it.
//
// **This lives outside `api/queries.ts` deliberately.** That module states
// "Nothing here transforms a response", and this hook does exactly one
// transformation: it reads the GLB's JSON chunk into the per-solid document
// (`glb.ts`). Keeping it here leaves that rule true where it is written, and
// puts the parse next to the module that defines what is legal to read.
//
// Caching: §2.6 makes the response `immutable` under an `ETag` naming the
// published GLB's own ref, so a fetched GLB is good forever — `staleTime:
// Infinity`, keyed by the requested ref. A first request on the server costs a
// tessellation and three offscreen ID-pass renders (the route mints the
// selection bundle on demand, §5.1); refetching it on a window focus would be a
// re-render of geometry that cannot have changed.

import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { apiBytes, refSegment } from "../api/client";
import { readGlbGeometry, type GlbGeometry } from "./glb";

/** `server/http/geometry.py::BUNDLE_HEADER` / `SOURCE_HEADER` — a closed pair. */
export const BUNDLE_HEADER = "X-Hephaestus-Selection-Bundle";
export const SOURCE_HEADER = "X-Hephaestus-Source-Artifact";

/** One published GLB: the bytes three.js loads, and the document this app reads. */
export interface LoadedGlb {
  /** The ref that was requested — the pin. */
  readonly requested_ref: string;
  /** The GLB bytes, handed to `GLTFLoader.parse` untouched. */
  readonly bytes: ArrayBuffer;
  /** Per-solid `solid_index` / `label` / `explode_offset` (§5.1). */
  readonly geometry: GlbGeometry;
  /**
   * The immutable selection bundle this GLB is linked to, **from the response
   * header** — never decoded out of `asset.extras`, which §1 makes a server
   * value and `geometry.py` publishes as a header for that reason.
   */
  readonly selection_bundle_ref: string | null;
  /** The build artifact the server resolved the GLB against (§12.3's `A`). */
  readonly source_artifact_ref: string | null;
}

export const glbKey = (ref: string): readonly unknown[] => ["artifacts", ref, "gltf"];

async function fetchGlb(ref: string): Promise<LoadedGlb> {
  const { bytes, headers } = await apiBytes(`/artifacts/${refSegment(ref)}/gltf`);
  return {
    requested_ref: ref,
    bytes,
    geometry: readGlbGeometry(bytes),
    selection_bundle_ref: headers.get(BUNDLE_HEADER),
    source_artifact_ref: headers.get(SOURCE_HEADER),
  };
}

/** The pinned build's GLB. Disabled until a ref is pinned. */
export function useGlb(ref: string | null): UseQueryResult<LoadedGlb, Error> {
  return useQuery({
    queryKey: glbKey(ref ?? ""),
    queryFn: () => fetchGlb(ref ?? ""),
    enabled: ref !== null,
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
  });
}
