// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The view cube (INTERFACE.md §5.5), top-right of the Stage.
//
// AMENDED 2026-09-03 — a Smith-style 3D cube: faces, edges, and corners are
// selectable. A face is a STANDARD_VIEWS axis (Front is `-Y` / `front`). The
// +++ corner is `iso`. Edges and other corners write the `az<deg>_el<deg>`
// grammar so every click is a camera `heph render` can reproduce. The seven
// labeled axis buttons (`+Y` `+Z` `-X` `iso` `+X` `-Z` `-Y`) are gone.

import { copy } from "../../../copy";
import { useWorkspace, workspaceStore } from "../../../state/react";
import { viewAngles } from "../../../viewport/cameras";
import styles from "./ViewCube.module.css";

const HALF = 28;

interface Hit {
  readonly key: string;
  readonly view: string;
  readonly kind: "face" | "edge" | "corner";
  readonly label: string;
  readonly transform: string;
  readonly dataView?: string;
}

function hits(): readonly Hit[] {
  const faces = copy.viewport.viewCube.faces;
  return [
    {
      key: "front",
      view: "front",
      kind: "face",
      label: faces.front,
      transform: `rotateY(0deg) translateZ(${HALF}px)`,
      dataView: "front",
    },
    {
      key: "back",
      view: "+Y",
      kind: "face",
      label: faces.back,
      transform: `rotateY(180deg) translateZ(${HALF}px)`,
    },
    {
      key: "right",
      view: "+X",
      kind: "face",
      label: faces.right,
      transform: `rotateY(90deg) translateZ(${HALF}px)`,
    },
    {
      key: "left",
      view: "-X",
      kind: "face",
      label: faces.left,
      transform: `rotateY(-90deg) translateZ(${HALF}px)`,
    },
    {
      key: "top",
      view: "+Z",
      kind: "face",
      label: faces.top,
      transform: `rotateX(90deg) translateZ(${HALF}px)`,
    },
    {
      key: "bottom",
      view: "-Z",
      kind: "face",
      label: faces.bottom,
      transform: `rotateX(-90deg) translateZ(${HALF}px)`,
    },
    {
      key: "iso",
      view: "iso",
      kind: "corner",
      label: copy.viewport.viewCube.iso,
      transform: `rotateX(35deg) rotateY(45deg) translateZ(${HALF * 1.2}px)`,
      dataView: "iso",
    },
    {
      key: "e-front-right",
      view: "az315_el0",
      kind: "edge",
      label: `${faces.front} / ${faces.right}`,
      transform: `rotateY(45deg) translateZ(${HALF}px)`,
    },
    {
      key: "e-front-left",
      view: "az225_el0",
      kind: "edge",
      label: `${faces.front} / ${faces.left}`,
      transform: `rotateY(-45deg) translateZ(${HALF}px)`,
    },
    {
      key: "e-front-top",
      view: "az270_el45",
      kind: "edge",
      label: `${faces.front} / ${faces.top}`,
      transform: `rotateX(45deg) translateZ(${HALF}px)`,
    },
    {
      key: "e-front-bottom",
      view: "az270_el-45",
      kind: "edge",
      label: `${faces.front} / ${faces.bottom}`,
      transform: `rotateX(-45deg) translateZ(${HALF}px)`,
    },
    {
      key: "c-tr",
      view: "az0_el35",
      kind: "corner",
      label: `${faces.right} / ${faces.top}`,
      transform: `rotateX(35deg) rotateY(0deg) translateZ(${HALF * 1.2}px)`,
    },
    {
      key: "c-tl",
      view: "az180_el35",
      kind: "corner",
      label: `${faces.left} / ${faces.top}`,
      transform: `rotateX(35deg) rotateY(180deg) translateZ(${HALF * 1.2}px)`,
    },
    {
      key: "c-br",
      view: "az0_el-35",
      kind: "corner",
      label: `${faces.right} / ${faces.bottom}`,
      transform: `rotateX(-35deg) rotateY(0deg) translateZ(${HALF * 1.2}px)`,
    },
    {
      key: "c-bl",
      view: "az180_el-35",
      kind: "corner",
      label: `${faces.left} / ${faces.bottom}`,
      transform: `rotateX(-35deg) rotateY(180deg) translateZ(${HALF * 1.2}px)`,
    },
  ];
}

export function ViewCube(): React.JSX.Element {
  const view = useWorkspace((s) => s.view);
  const angles = viewAngles(view);
  const azimuth = angles?.azimuth_deg ?? 45;
  const elevation = angles?.elevation_deg ?? 35;
  const cubeTransform = `rotateX(${-elevation}deg) rotateZ(${-azimuth}deg)`;
  const targets = hits();

  return (
    <div
      className={styles["cube"]}
      data-view-cube=""
      role="group"
      tabIndex={0}
      aria-label={copy.viewport.viewCube.label}
    >
      <div className={styles["scene"]}>
        <div className={styles["body"]} style={{ transform: cubeTransform }}>
          {targets.map((hit) => (
            <button
              key={hit.key}
              type="button"
              className={styles[hit.kind]}
              style={{ transform: hit.transform }}
              aria-label={hit.label}
              data-cube-hit={hit.kind}
              {...(hit.dataView === undefined ? {} : { "data-view": hit.dataView })}
              {...(view === hit.view ? { "data-cube-current": "" } : {})}
              onClick={() => {
                workspaceStore.update({ view: hit.view });
              }}
            >
              {hit.kind === "face" || hit.key === "iso" ? hit.label : ""}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
