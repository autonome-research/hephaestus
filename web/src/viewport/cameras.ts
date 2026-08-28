// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The camera vocabulary, mirrored from `core/render/cameras.py` (INTERFACE.md
// §5.5).
//
// §5.5: "The view cube drives `view` through the `STANDARD_VIEWS` vocabulary of
// `core/render/cameras.py` plus its `az<deg>_el<deg>` grammar, **so a view named
// in the UI is a view `heph render` can reproduce**; free orbit snapshots the
// nearest `az/el` into workspace state, keeping every reachable camera
// nameable."
//
// That last clause is why this file exists at all. A viewport with a free camera
// and no naming rule produces screenshots nobody can ask the server to
// reproduce; every camera this viewport can reach has a name in the server's own
// grammar, and the name is what lands in workspace state and in the URL.
//
// WHAT IS MIRRORED, AND WHY MIRRORING IS NOT DUPLICATION. Mission rule 6 forbids
// a second implementation of a *contract*. A camera direction is not a contract
// value: it is the screen-space quantity §1 hands to the client outright ("The
// client may compute **screen-space** quantities … camera transforms"). What
// must not diverge is the **vocabulary and its angles**, so those are
// transcribed here verbatim from `cameras.py:47-56` with the source line cited,
// and `web/test/cameras.test.ts` pins the eight names and their angles against
// that transcription. The server never sends a camera to the browser and the
// browser never sends one back: `view` crosses the wire as a *name*.
//
// Frame convention, also from `cameras.py`: the world is **Z-up**. Azimuth
// rotates about +Z from +X toward +Y; elevation lifts from the XY plane toward
// +Z; the eye sits on the + side named by the axis views.

import { STANDARD_VIEWS, type StandardView } from "../state/workspace";

/** Classic isometric elevation `atan(1/sqrt(2))` in degrees (`cameras.py`:41). */
export const ISO_ELEVATION_DEG = (Math.atan(1 / Math.SQRT2) * 180) / Math.PI;

/** An azimuth/elevation pair in degrees — the server's `ViewSpec` angles. */
export interface ViewAngles {
  readonly azimuth_deg: number;
  readonly elevation_deg: number;
}

/**
 * `cameras.py::STANDARD_VIEWS` (`:47-56`), transcribed.
 *
 * Keyed by `StandardView` so a name added to the workspace vocabulary without an
 * angle here is a type error rather than a camera that silently falls back.
 */
export const VIEW_ANGLES: Readonly<Record<StandardView, ViewAngles>> = {
  iso: { azimuth_deg: 45, elevation_deg: ISO_ELEVATION_DEG },
  "+X": { azimuth_deg: 0, elevation_deg: 0 },
  "-X": { azimuth_deg: 180, elevation_deg: 0 },
  "+Y": { azimuth_deg: 90, elevation_deg: 0 },
  "-Y": { azimuth_deg: 270, elevation_deg: 0 },
  "+Z": { azimuth_deg: 0, elevation_deg: 90 },
  "-Z": { azimuth_deg: 0, elevation_deg: -90 },
  front: { azimuth_deg: 270, elevation_deg: 0 },
};

/** `cameras.py`'s grammar (`:58`), narrowed to what a URL may carry. */
const GRAMMAR = /^az(-?\d+(?:\.\d+)?)_el(-?\d+(?:\.\d+)?)$/;

const DEG = Math.PI / 180;

/** Resolve a `view` string to its angles, or `null` if it names no camera. */
export function viewAngles(view: string): ViewAngles | null {
  if ((STANDARD_VIEWS as readonly string[]).includes(view)) {
    return VIEW_ANGLES[view as StandardView];
  }
  const match = GRAMMAR.exec(view);
  if (match === null) return null;
  return { azimuth_deg: Number(match[1]), elevation_deg: Number(match[2]) };
}

/** Unit vector from the geometry centre toward the eye (`ViewSpec.eye_direction`). */
export function eyeDirection(angles: ViewAngles): readonly [number, number, number] {
  const az = angles.azimuth_deg * DEG;
  const el = angles.elevation_deg * DEG;
  const cosEl = Math.cos(el);
  return [cosEl * Math.cos(az), cosEl * Math.sin(az), Math.sin(el)];
}

/**
 * The up hint `camera_framing` uses: world +Z, except when the view axis is
 * (anti)parallel to +Z, where it is +Y (`cameras.py`:176-181).
 */
export function upHint(direction: readonly [number, number, number]): readonly [number, number, number] {
  return Math.abs(direction[2]) > 0.999 ? [0, 1, 0] : [0, 0, 1];
}

/** Angles back out of a unit eye direction — the free-orbit inverse. */
export function anglesFromDirection(
  direction: readonly [number, number, number],
): ViewAngles {
  const [x, y, z] = direction;
  const length = Math.hypot(x, y, z);
  if (length === 0) return { azimuth_deg: 0, elevation_deg: 0 };
  const elevation = Math.asin(Math.min(1, Math.max(-1, z / length))) / DEG;
  let azimuth = Math.atan2(y, x) / DEG;
  if (azimuth < 0) azimuth += 360;
  return { azimuth_deg: azimuth, elevation_deg: elevation };
}

/**
 * §5.5's "free orbit snapshots the nearest `az/el` into workspace state".
 *
 * Angles are rounded to whole degrees: the grammar accepts decimals, but a name
 * that changes on every pointer move would push a new URL per frame and would
 * make "the same view" untypable. Whole degrees is the coarsest rounding that
 * still names every distinguishable camera, and it is what a human can retype.
 *
 * The **name is canonical** for a standard view: an orbit that lands exactly on
 * one of the eight returns that name, so a view cube click followed by a nudge
 * back does not leave the workspace holding `az45_el35` for `iso`.
 *
 * `cameras.py` gives `-Y` and `front` **the same angles** (270°, 0°), so those
 * two names are one camera and the snapshot cannot tell them apart. It returns
 * the first in `STANDARD_VIEWS` order — `-Y` — deterministically rather than
 * guessing at intent; both names still resolve to that camera on the way in, so
 * a URL saying `front` keeps saying `front` until the user orbits away from it.
 */
export function nameForDirection(direction: readonly [number, number, number]): string {
  const angles = anglesFromDirection(direction);
  const azimuth = normalizeAzimuth(Math.round(angles.azimuth_deg));
  const elevation = Math.round(angles.elevation_deg);
  for (const name of STANDARD_VIEWS) {
    const standard = VIEW_ANGLES[name];
    if (
      normalizeAzimuth(Math.round(standard.azimuth_deg)) === azimuth &&
      Math.round(standard.elevation_deg) === elevation
    ) {
      return name;
    }
  }
  return `az${azimuth}_el${elevation}`;
}

function normalizeAzimuth(degrees: number): number {
  const wrapped = degrees % 360;
  return wrapped < 0 ? wrapped + 360 : wrapped;
}
