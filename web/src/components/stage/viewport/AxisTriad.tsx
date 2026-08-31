// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The axis triad (INTERFACE.md §3.11.6), bottom-left of the Stage.
//
// §3.11.6: "Axis triad, bottom-left, in the Z-up frame `engine.ts` already
// establishes." Two decisions in it are not obvious and both are argued here
// rather than discovered by the next reader.
//
// ── IT IS DOM, NOT WEBGL, AND THAT IS THE POINT ─────────────────────────────
//
// A triad has to say *which* axis, and "which" is a letter. Drawing a letter in
// WebGL means a font atlas or a canvas texture — a second text pipeline, in a
// bundle §3.12 already refuses an icon font for. The alternative is the CAD
// convention of three saturated hues, and that is worse here than it is
// anywhere: §3.9 spends exactly one accent hue plus five **status** hues, and in
// that vocabulary red means `fail`. A red axis in the corner of an instrument
// whose badges use red for a failed check is a colour saying two things.
//
// So the triad is three lines and three letters in the chrome layer, where the
// type roles and the ink tokens the §3.14 checks already police apply to it for
// free, and where its colours are *checked* rather than asserted. Colour never
// replaces the letter — §3.12's own rule about icons and words, one layer down.
//
// The projection is honest about the frame: `engine.cameraBasis()` returns the
// three world axes as screen-space unit vectors in the camera's **Z-up** basis,
// so the triad rotates with the same camera `heph render` can reproduce.
//
// ── AND IT UPDATES OUTSIDE REACT, ON PURPOSE ────────────────────────────────
//
// An orbit drag draws a frame per rAF. Turning each of those into a `setState`
// would re-render a subtree sixty times a second to move three lines, and §5.5's
// camera-settle write already exists precisely to keep the orbit *out* of
// workspace state. So this component subscribes to the engine's frame signal and
// writes the three transforms straight onto its own DOM nodes. React owns
// mounting it; the camera owns its attributes. Nothing else in the app reads
// them, and nothing here is a `<Fact>` — a unit vector is the screen-space class
// §1 hands the client outright, and no model quantity survives normalization.

import { useEffect, useRef } from "react";
import { copy } from "../../../copy";
import type { ViewportEngine } from "../../../viewport/engine";
import styles from "./AxisTriad.module.css";

/** The three axes, in the order they are drawn when nothing overlaps. */
const AXES = ["x", "y", "z"] as const;
type Axis = (typeof AXES)[number];

/** Half the SVG's side, in its own user units. The origin sits here. */
const CENTRE = 24;

/** How far a full-length axis reaches from the origin, in user units. */
const REACH = 15;

/** Where the letter sits, as a fraction past the line's tip. */
const LABEL_REACH = 1.42;

export interface AxisTriadProps {
  /** The live engine, or `null` before it exists / after it is disposed. */
  readonly engine: ViewportEngine | null;
  /** §5.5's operator toggle. Default on — the authored picture. */
  readonly visible?: boolean;
}

export function AxisTriad({ engine, visible = true }: AxisTriadProps): React.JSX.Element {
  const lines = useRef<Partial<Record<Axis, SVGLineElement | null>>>({});
  const labels = useRef<Partial<Record<Axis, SVGTextElement | null>>>({});

  useEffect(() => {
    if (engine === null) return;
    const paint = (): void => {
      for (const entry of engine.cameraBasis()) {
        const [dx, dy] = entry.screen;
        const line = lines.current[entry.axis];
        const label = labels.current[entry.axis];
        if (line !== null && line !== undefined) {
          line.setAttribute("x2", String(CENTRE + dx * REACH));
          line.setAttribute("y2", String(CENTRE + dy * REACH));
          // An axis pointing away from the viewer is drawn dimmer rather than
          // hidden: an axis that vanished at the halfway point would read as a
          // broken triad, and "pointing away" is exactly what a reader wants to
          // know when two axes overlap on screen.
          line.setAttribute("data-axis-facing", entry.depth >= 0 ? "toward" : "away");
        }
        if (label !== null && label !== undefined) {
          label.setAttribute("x", String(CENTRE + dx * REACH * LABEL_REACH));
          label.setAttribute("y", String(CENTRE + dy * REACH * LABEL_REACH));
          label.setAttribute("data-axis-facing", entry.depth >= 0 ? "toward" : "away");
        }
      }
    };
    paint();
    return engine.onFrame(paint);
  }, [engine]);

  return (
    <svg
      className={styles["triad"]}
      data-axis-triad=""
      {...(visible ? {} : { "data-axis-hidden": "" })}
      viewBox={`0 0 ${String(CENTRE * 2)} ${String(CENTRE * 2)}`}
      role="img"
      aria-label={copy.viewport.triad.label}
      aria-hidden={!visible}
    >
      {AXES.map((axis) => (
        <line
          key={axis}
          ref={(node) => {
            lines.current[axis] = node;
          }}
          className={styles["axis"]}
          data-axis={axis}
          x1={CENTRE}
          y1={CENTRE}
          x2={CENTRE}
          y2={CENTRE}
        />
      ))}
      {AXES.map((axis) => (
        <text
          key={axis}
          ref={(node) => {
            labels.current[axis] = node;
          }}
          className={styles["label"]}
          data-axis-label={axis}
          x={CENTRE}
          y={CENTRE}
          textAnchor="middle"
          dominantBaseline="central"
        >
          {copy.viewport.triad.axis[axis]}
        </text>
      ))}
    </svg>
  );
}
