// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The section plane spec, and the clipping half-space that previews it
// (INTERFACE.md §5.3).
//
// §5.3 splits section into two surfaces that must not be confused:
//
// * the **plate** — a *server*-rendered PNG from
//   `render_channel(..., channel="section")`, displayed as a fitted image layer,
//   `data-section-state="rendered"`. This is the evidentiary surface: G4.7
//   compares it against an existing golden, and it is server pixels because "a
//   headless-Chromium WebGL render is a **different rasterizer** and will not
//   match them".
// * the **live clipping preview** — three.js clipping planes while the control
//   is dragged, `data-section-state="preview"`, **never** golden-compared.
//
// This module owns the grammar both sides agree on and the half-space the
// preview clips to. It renders nothing and fetches nothing.
//
// THE GRAMMAR, from `core/render/channels.py::parse_section_plane` (`:444-489`):
// `[±]AXIS@OFFSET`, where the leading sign chooses which half is **removed** —
// "`+Z@…` cuts away the `+Z` half and shows the top-down cross-section". The
// retained half is therefore `sign · (coord − offset) <= 0`.
//
// §4.5's URL codec accepts a **narrower** spelling than the server's parser: an
// explicit sign and a numeric offset (`SECTION_PLANE` in `state/workspace.ts`),
// with no `c`/`center`/`mid`/`h` centre keyword and no case folding. That is
// deliberate and it is a narrowing, never a widening — every string this module
// produces parses on the server, and a centre keyword is resolved to a number by
// the control before it reaches workspace state, because a URL that means
// "wherever the middle is" would name a different plane for a different build.

/** The three axes the grammar admits, in `parse_section_plane`'s own order. */
export const SECTION_AXES = ["X", "Y", "Z"] as const;
export type SectionAxis = (typeof SECTION_AXES)[number];

/** A parsed `[±]AXIS@OFFSET`. `sign` names the half that is **removed**. */
export interface SectionPlaneSpec {
  readonly axis: SectionAxis;
  readonly sign: 1 | -1;
  readonly offset: number;
  /** The canonical spelling this spec round-trips to. */
  readonly spec: string;
}

const SPEC = /^([+-])([XYZ])@(-?\d+(?:\.\d+)?)$/;

/** Parse the workspace spelling of a section plane, or `null` if it is not one. */
export function parseSectionPlane(spec: string): SectionPlaneSpec | null {
  const match = SPEC.exec(spec);
  if (match === null) return null;
  const axis = match[2] as SectionAxis;
  const sign: 1 | -1 = match[1] === "-" ? -1 : 1;
  const offset = Number(match[3]);
  if (!Number.isFinite(offset)) return null;
  return { axis, sign, offset, spec: formatSectionPlane(sign, axis, offset) };
}

/**
 * The canonical spelling. Offsets are rendered with at most three decimals so a
 * dragged control cannot push a 17-digit float into the URL, and trailing zeros
 * are trimmed so `30` stays `30` rather than becoming `30.000`.
 */
export function formatSectionPlane(sign: 1 | -1, axis: SectionAxis, offset: number): string {
  // `String` of a rounded float already drops trailing zeros (`30` not `30.000`)
  // and never reaches exponent form in the millimetre ranges a part occupies.
  const rounded = Math.round(offset * 1000) / 1000;
  return `${sign === -1 ? "-" : "+"}${axis}@${String(rounded === 0 ? 0 : rounded)}`;
}

/** A half-space in three.js's convention: keep where `normal · p + constant >= 0`. */
export interface ClippingHalfSpace {
  readonly normal: readonly [number, number, number];
  readonly constant: number;
}

const AXIS_INDEX: Readonly<Record<SectionAxis, 0 | 1 | 2>> = { X: 0, Y: 1, Z: 2 };

/**
 * The half-space the preview keeps, agreeing with the server's cut.
 *
 * Derivation, written out because a sign error here is a preview that shows the
 * *other* half and looks entirely plausible:
 *
 *   server keeps  `sign · (p_axis − offset) <= 0`
 *   three.js keeps `n · p + c >= 0`
 *
 * so `n = −sign · e_axis` and `c = sign · offset`:
 *   `−sign · p_axis + sign · offset >= 0`
 *   ⇔ `sign · (offset − p_axis) >= 0`
 *   ⇔ `sign · (p_axis − offset) <= 0`   ∎
 */
export function clippingHalfSpace(plane: SectionPlaneSpec): ClippingHalfSpace {
  const normal: [number, number, number] = [0, 0, 0];
  normal[AXIS_INDEX[plane.axis]] = -plane.sign;
  return { normal, constant: plane.sign * plane.offset };
}

/** Whether a point is retained by `plane` — the same inequality, for tests. */
export function retains(plane: SectionPlaneSpec, point: readonly [number, number, number]): boolean {
  const coordinate = point[AXIS_INDEX[plane.axis]];
  return plane.sign * (coordinate - plane.offset) <= 0;
}
