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

import { useMemo, useState } from "react";
import { copy } from "../../../copy";
import { useWorkspace, workspaceStore } from "../../../state/react";
import { eyeDirection, VIEW_ANGLES, viewAngles } from "../../../viewport/cameras";
import {
  CUBE_SIZE,
  projectTargets,
  targetName,
  type CubeTarget,
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
  const view = useWorkspace((s) => s.view);
  // An unparseable `view` cannot happen through the store's own validator; the
  // iso fallback is here so a hand-edited URL draws a cube rather than nothing.
  const angles = viewAngles(view) ?? VIEW_ANGLES.iso;
  const azimuth = angles.azimuth_deg;
  const elevation = angles.elevation_deg;
  const [focused, setFocused] = useState<string | null>(null);

  const targets = useMemo(
    () =>
      projectTargets(azimuth, elevation)
        .filter((target) => target.visible)
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

  return (
    <div
      className={styles["cube"]}
      data-view-cube=""
      role="group"
      tabIndex={0}
      aria-label={copy.viewport.viewCube.label}
    >
      <div className={styles["scene"]}>
        <svg className={styles["art"]} viewBox={viewBox} aria-hidden="true" focusable="false">
          {targets.map((target) => (
            <polygon
              key={target.key}
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
