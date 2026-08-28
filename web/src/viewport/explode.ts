// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The explode transform, client side (INTERFACE.md §5.2), in one function.
//
// §1: "**Explode is a client transform over a server-declared displacement.**
// The GLTF ships each solid's **`explode_offset`** — the full displacement
// vector at `t = 1` … The client applies `offset · t` and nothing else. It does
// not compute centroids, does not normalize, and does not reconstruct a
// magnitude."
//
// That is the whole of this module, and it is a module rather than three lines
// inlined into the slider because the server states a **byte-equivalence
// invariant** over it (§5.1: "for every solid and every `t`, the client's
// `explode_offset · t` is byte-equivalent to `_explode_offset(scene, solid,
// t)`"). An invariant with two client-side spellings is an invariant with a
// place to drift.
//
// THE ONE PLACE THE TWO SIDES COULD DISAGREE, and how it is closed here.
// `channels.py::_explode_offset` short-circuits `t <= 0` to `+0.0` in every
// component so the zero displacement has a single representation. A plain
// `offset · t` does not: `-1.5 * 0` is `-0`, which is the same displacement and
// different bytes. The server-side pytest excludes `t = 0` from its byte
// comparison for exactly this reason. This function **mirrors the
// short-circuit** instead, so the two sides agree at `t = 0` as well and the
// excluded case stops being excluded on the client's account.

/** A displacement vector: the GLB's `extras.explode_offset`, or a scaling of it. */
export type Displacement = readonly [number, number, number];

/** The zero displacement, spelled `+0.0` in every component (see the header). */
export const NO_DISPLACEMENT: Displacement = [0, 0, 0];

/**
 * `offset · t` — the client's entire share of the explode transform (§5.2).
 *
 * `t <= 0` returns `+0.0` in every component, mirroring
 * `core/render/channels.py::_explode_offset`'s own short-circuit.
 */
export function explodeTranslation(offset: Displacement, t: number): Displacement {
  if (!Number.isFinite(t) || t <= 0) return NO_DISPLACEMENT;
  return [offset[0] * t, offset[1] * t, offset[2] * t];
}
