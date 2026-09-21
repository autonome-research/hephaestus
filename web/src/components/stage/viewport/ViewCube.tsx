// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The view cube (INTERFACE.md §5.5), top-right of the Stage.
//
// AMENDED 2026-09-03 — a Smith-style cube: faces, edges, and corners are
// selectable. A face is a STANDARD_VIEWS axis (Front is `-Y` / `front`). The
// +++ corner is `iso`. Edges and other corners write the `az<deg>_el<deg>`
// grammar so every click is a camera `heph render` can reproduce. The seven
// labeled axis buttons (`+Y` `+Z` `-X` `iso` `+X` `-Z` `-Y`) are gone.
//
// CORRECTED 2026-09-04 (`docs/audit-2026-09-04-broken.md` B-7). Three defects
// lived in this one component and only the third is a layout bug:
//
//   * the parent transform was `rotateX(-el) rotateZ(-az)`, and `rotateZ` is a
//     roll in the SCREEN plane, so azimuth never turned the cube on its
//     vertical axis — `Front` faced the viewer at every azimuth and `Back` was
//     culled at every azimuth;
//   * the edges and corners were `inset: 0` slabs and plates through the body's
//     INTERIOR, so hit testing resolved by paint order and nine of fifteen
//     targets were unreachable even with the transform corrected;
//   * the `view` strings were HAND-WRITTEN beside `cameras.ts`, which already
//     owns the naming rule — the button labelled "Right / Top" carried
//     `az0_el35`, a camera above the `+X` face. A user clicking it got a
//     picture `heph render` reproduces as something else, which is an honesty
//     failure and not a layout one.
//
// The whole hit model now comes from `viewport/cubeTargets.ts`: one projection
// produces the drawn cell and the clickable region, and `cameras.ts` names it.
// This file only renders that, and it renders EXACTLY the visible cells —
// §5.5's negative half, "a target that is drawn is hittable, and a target that
// is not drawn is not". A face turned away from the viewer is not drawn and not
// clickable, the way it is on any orientation cube; it is reached by turning
// the cube, which is what the edge and corner targets are for.

import { useMemo, useState, useSyncExternalStore } from "react";
import { copy } from "../../../copy";
import { workspaceStore } from "../../../state/react";
import { cameraPoseStore } from "../../../state/cameraPose";
import { eyeDirection } from "../../../viewport/cameras";
import {
  CUBE_SIZE,
  projectAxes,
  projectTargets,
  targetName,
  type CubeTarget,
  type ProjectedAxis,
  type ProjectedTarget,
} from "../../../viewport/cubeTargets";
import { cx } from "../../../system/dataAttrs";
import styles from "./ViewCube.module.css";

const HALF = CUBE_SIZE / 2;

/**
 * The face word for one signed axis. §3's rule that every string lives in
 * `copy.ts` is why this is a lookup and not six literals; the six words already
 * compose every edge and corner name, so the cube needs no new strings.
 */
function faceWord(axisIndex: number, sign: number): string {
  const faces = copy.viewport.viewCube.faces;
  if (axisIndex === 0) return sign > 0 ? faces.right : faces.left;
  if (axisIndex === 1) return sign > 0 ? faces.back : faces.front;
  return sign > 0 ? faces.top : faces.bottom;
}

/**
 * A target's accessible name: the face word for a face, those words joined for
 * an edge or a corner, and `copy.viewport.viewCube.iso` for the `+++` corner —
 * the one target whose camera has a name of its own. That string is no longer
 * DRAWN (it clipped at 14px in the shipped cube); it survives as this name.
 */
export function cubeTargetLabel(target: CubeTarget): string {
  if (target.view === "iso") return copy.viewport.viewCube.iso;
  const words: string[] = [];
  target.axis.forEach((component, index) => {
    if (component !== 0) words.push(faceWord(index, component));
  });
  return words.join(" / ");
}

function pointsOf(polygon: readonly (readonly [number, number])[]): string {
  return polygon.map(([x, y]) => `${String(x)},${String(y)}`).join(" ");
}

function clipOf(target: ProjectedTarget): string {
  const points = target.clip.map(([x, y]) => `${String(x)}px ${String(y)}px`).join(", ");
  return `polygon(${points})`;
}

export function ViewCube(): React.JSX.Element {
  // THE LIVE CAMERA, not the named view (2026-09-20). `workspace.view` is
  // written when a drag SETTLES, so reading it left the cube motionless
  // through an orbit and then snapping between eight poses — which is what
  // "rotates as a rectangle, slow and janky" was. `state/cameraPose.ts` is
  // published from the viewport's frame callback and follows the pointer.
  const pose = useSyncExternalStore(
    cameraPoseStore.subscribe,
    cameraPoseStore.getSnapshot,
    cameraPoseStore.getSnapshot,
  );
  const azimuth = pose.azimuth_deg;
  const elevation = pose.elevation_deg;
  const [focused, setFocused] = useState<string | null>(null);

  const targets = useMemo(
    () =>
      projectTargets(azimuth, elevation)
        .filter((target) => target.visible && target.kind === "face")
        // Nearest last. The cells tile the silhouette and never overlap, so
        // this is order for its own sake rather than a fix for one — but it
        // keeps the DOM order the depth order a reader would expect.
        .sort((a, b) => a.depth - b.depth),
    [azimuth, elevation],
  );

  // The camera the workspace is on, named through the SAME rule the targets
  // are, so `-Y` and `front` — one camera, two names — cannot disagree about
  // which cell is current.
  const current = targetName(eyeDirection({ azimuth_deg: azimuth, elevation_deg: elevation }));
  const focusedTarget = targets.find((target) => target.key === focused);
  const viewBox = `${String(-HALF)} ${String(-HALF)} ${String(CUBE_SIZE)} ${String(CUBE_SIZE)}`;
  // 0.5 of the half-cube: long enough to read as an axis, short enough that the
  // letter lands inside the FRONT faces at every camera rather than out on the
  // silhouette where the face words are. At 0.62 the X and Y tips sat on top of
  // "Right" and "Back" (2026-09-20).
  // 2.6 of the half-cube, and the number has to be this large because the
  // PROJECTION FORESHORTENS EACH AXIS DIFFERENTLY. An isometric cube projects
  // about 1.22 half-edges to its silhouette, but a world axis pointing at a
  // cube corner projects at about 0.707 of its length — so at 1.8 the +X arm
  // came out SHORTER than the outline it had to clear and was swallowed
  // whole, while +Z (0.816) just peeked out. 2.6 puts the most foreshortened
  // arm clear of the silhouette, which is what makes all three visible.
  const axes = useMemo(() => projectAxes(azimuth, elevation, 3.15), [azimuth, elevation]);

  return (
    <div
      className={styles["cube"]}
      data-view-cube=""
      role="group"
      tabIndex={0}
      aria-label={copy.viewport.viewCube.label}
    >
      <div className={styles["scene"]}>
        {/* The axes, FIRST so they paint UNDER the cube (2026-09-20): the
            arms that reach past the silhouette are all that shows, which is
            the reference's arrangement — three coloured stubs on a solid
            block, not a triad drawn through its middle.

            They are in the SAME basis as the cells — an indicator with
            its own projection is a second answer to "which way is +X", and the
            two drift the moment either is touched. Drawn behind the labels so a
            face word is never crossed by a line, and monochrome because the
            viewport does not spend a status colour on decoration (§3.11.6). */}
        <svg className={styles["axes"]} viewBox={viewBox} aria-hidden="true" focusable="false">
          {axes.map((axis: ProjectedAxis) => (
            <g
              key={axis.label}
              className={styles[`axis${axis.label}`]}
              data-axis={axis.label}
              data-axis-facing={axis.depth >= 0 ? "toward" : "away"}
            >
              <line className={styles["axisLine"]} x1={0} y1={0} x2={axis.tip[0]} y2={axis.tip[1]} />
              {/* Scaled by a TRANSFORM rather than a font size. The axis
                  letter and the face word take the same type role (§3.8 owns
                  the ramp; `heph/no-raw-type` is why neither names a size),
                  but a 72-unit cube renders that role at the same pixels as
                  the face words — so the triad read as loud as the faces it
                  annotates. The face words already solve this: they are drawn
                  at the origin inside a `matrix(...)` that carries their size.
                  This does the same, one transform instead of a second ramp. */}
              <g transform={`translate(${String(axis.text[0])} ${String(axis.text[1])}) scale(0.62)`}>
                <text
                  className={styles["axisWord"]}
                  x={0}
                  y={0}
                  textAnchor="middle"
                  dominantBaseline="central"
                >
                  {axis.label}
                </text>
              </g>
            </g>
          ))}
        </svg>
        <svg className={styles["art"]} viewBox={viewBox} aria-hidden="true" focusable="false">
          {targets.map((target) => (
            <polygon
              key={target.key}
              // Which world axis this face looks along, so the stylesheet can
              // shade it. `axis` is the direction vector: exactly one
              // component is non-zero for a face.
              data-cube-facing={
                target.axis[2] !== 0 ? "z" : target.axis[1] !== 0 ? "y" : "x"
              }
              className={cx(
                styles["cell"],
                styles[
                  target.kind === "face" ? "cellFace" : target.kind === "edge" ? "cellEdge" : "cellCorner"
                ],
              )}
              points={pointsOf(target.polygon)}
            />
          ))}
        </svg>
        {targets.map((target) => (
          <button
            key={target.key}
            type="button"
            className={styles[target.kind]}
            style={{
              left: `${String(target.box.left)}px`,
              top: `${String(target.box.top)}px`,
              width: `${String(target.box.width)}px`,
              height: `${String(target.box.height)}px`,
              clipPath: clipOf(target),
            }}
            aria-label={cubeTargetLabel(target)}
            data-view={target.view}
            data-cube-hit={target.kind}
            {...(current === target.view ? { "data-cube-current": "" } : {})}
            onFocus={() => {
              setFocused(target.key);
            }}
            onBlur={() => {
              setFocused(null);
            }}
            onClick={() => {
              workspaceStore.update({ view: target.view });
            }}
          />
        ))}
        <svg className={styles["gloss"]} viewBox={viewBox} aria-hidden="true" focusable="false">
          {targets.map((target) =>
            target.frame === null ? null : (
              <g key={target.key} transform={`matrix(${target.frame.map(String).join(" ")})`}>
                <text className={styles["word"]} x={0} y={0} textAnchor="middle" dominantBaseline="central">
                  {cubeTargetLabel(target)}
                </text>
              </g>
            ),
          )}
          {focusedTarget === undefined ? null : (
            <polygon className={styles["ring"]} points={pointsOf(focusedTarget.polygon)} />
          )}
        </svg>
      </div>
    </div>
  );
}
