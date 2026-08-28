// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The scene-graph handle the Playwright harness reads (INTERFACE.md §5.2, G4.6).
//
// G4.6 is asserted by "reading pairwise centroid distances back out of the scene
// graph" (§5.2). A scene graph is not a DOM node, so unlike every other gate
// clause it cannot be read through a `data-*` attribute — the harness needs a
// handle on the live three.js tree. This module is that handle and nothing else.
//
// WHY THIS IS NOT A §1 VIOLATION, stated rather than assumed. §1's rule is about
// values that "appear in a result, a badge, a readout, a provenance answer, or a
// selection". Nothing here appears anywhere: no component imports this module's
// output, no `<Fact>` sources it, and the pairwise **subtraction** G4.6 asserts
// on is performed by the harness, not by the app — the same division of labour
// §5.4 spells out for the mask delta ("All three steps run in the **test
// harness**, never in the workspace"). What crosses this boundary is a
// **position**, which §1 hands the client outright as a screen-space quantity,
// and the workspace's own use of that position is to place a mesh.
//
// It ships in production builds on purpose: the gate runs `pnpm test:e2e`
// against a real `heph serve --web` serving the built bundle (§14), so a
// dev-only handle would be a handle the gate cannot reach. Making it read-only
// and side-effect-free is what keeps that safe — every function returns a fresh
// plain-JSON snapshot, and nothing on the handle can change what is rendered.

import type { SolidIndex } from "./scene";
import { solidCentroids } from "./scene";

/** The global name the handle is published under. Namespaced, and stable. */
export const VIEWPORT_HANDLE = "__hephaestus_viewport__";

/** One solid, as the harness sees it. Plain JSON: `page.evaluate` returns it. */
export interface ViewportSolidSnapshot {
  readonly solid_index: number;
  readonly mesh_index: number;
  readonly label: string | null;
  readonly visible: boolean;
  /** The node's current translation — `explode_offset · t` (§5.2). */
  readonly position: readonly [number, number, number];
  /** World-space bounding-box centre. G4.6's input; never rendered. */
  readonly centroid: readonly [number, number, number] | null;
  /** The server's declared displacement at `t = 1`, carried through verbatim. */
  readonly explode_offset: readonly [number, number, number];
}

/** What the harness finds at `window.__hephaestus_viewport__`. */
export interface ViewportHandle {
  /** The artifact ref whose GLB is loaded, or `null` before one is. */
  readonly artifact_ref: string | null;
  /** The scene's solids. A snapshot: calling again re-reads the live graph. */
  solids(): readonly ViewportSolidSnapshot[];
}

interface HandleWindow {
  [VIEWPORT_HANDLE]?: ViewportHandle;
}

/** Read the current scene as plain JSON. Returns `[]` before a GLB is loaded. */
export function snapshotSolids(index: SolidIndex | null): readonly ViewportSolidSnapshot[] {
  if (index === null) return [];
  const centroids = solidCentroids(index);
  return index.nodes.map((node) => {
    const centroid = centroids.get(node.solid.solid_index) ?? null;
    return {
      solid_index: node.solid.solid_index,
      mesh_index: node.solid.mesh_index,
      label: node.solid.label,
      visible: node.object.visible,
      position: [node.object.position.x, node.object.position.y, node.object.position.z] as const,
      centroid,
      explode_offset: node.solid.explode_offset,
    };
  });
}

/**
 * Publish the handle. `read` is called on every access, so the harness always
 * sees the live scene rather than whatever it looked like at mount.
 */
export function installViewportHandle(read: () => {
  index: SolidIndex | null;
  artifactRef: string | null;
}): () => void {
  const handle: ViewportHandle = {
    get artifact_ref() {
      return read().artifactRef;
    },
    solids: () => snapshotSolids(read().index),
  };
  const host = window as unknown as HandleWindow;
  host[VIEWPORT_HANDLE] = handle;
  return () => {
    delete host[VIEWPORT_HANDLE];
  };
}
