// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The section control (INTERFACE.md §5.3).
//
// It writes two workspace fields and nothing else:
//
//   section_plane     "[+-]AXIS@OFFSET"  — which cut
//   channel_overlay   "none" | "section" — whether the **server's plate** is up
//
// and the second is §5.3's whole distinction made into state. While
// `channel_overlay` is `"none"` the Stage shows the browser's clipping preview,
// marked `data-section-state="preview"` and **never** golden-compared. Clicking
// *Render section* sets `"section"`, which asks the server for the plate and
// marks the Stage `"rendered"`. Touching the axis, the side, or the offset drops
// straight back to `"none"`: a plate for a plane the user has since moved is a
// picture of a different cut, and §5.3's asymmetry only holds if the labelling is
// exact.
//
// THE OFFSET, and why it is a number rather than a keyword. `parse_section_plane`
// accepts `c`/`center`/`mid`/`h` for the bounding-box midpoint, and §4.5's URL
// codec does not. That narrowing is deliberate: a URL meaning "wherever the
// middle is" names a *different plane* for a different build, and this
// workspace's central object is an artifact ref precisely so a link does not
// drift. The control resolves the midpoint against the loaded scene's bounds and
// writes the resolved number.

import { copy } from "../../../copy";
import { useWorkspace, workspaceStore } from "../../../state/react";
import {
  SECTION_AXES,
  formatSectionPlane,
  parseSectionPlane,
  type SectionAxis,
} from "../../../viewport/section";
import styles from "./SectionControl.module.css";

export interface SceneBounds {
  readonly min: readonly [number, number, number];
  readonly max: readonly [number, number, number];
}

export interface SectionControlProps {
  /** The loaded scene's bounds, or `null` before a GLB is up. */
  readonly bounds: SceneBounds | null;
}

const AXIS_INDEX: Readonly<Record<SectionAxis, 0 | 1 | 2>> = { X: 0, Y: 1, Z: 2 };

/** The offset range and step for one axis, from the scene's own extent. */
function axisRange(bounds: SceneBounds | null, axis: SectionAxis): {
  min: number;
  max: number;
  step: number;
} {
  if (bounds === null) return { min: -100, max: 100, step: 0.5 };
  const i = AXIS_INDEX[axis];
  const min = bounds.min[i];
  const max = bounds.max[i];
  const span = max - min;
  return { min, max, step: span > 0 ? Math.max(span / 200, 0.001) : 0.5 };
}

export function SectionControl({ bounds }: SectionControlProps): React.JSX.Element {
  const spec = useWorkspace((s) => s.section_plane);
  const overlay = useWorkspace((s) => s.channel_overlay);
  const plane = spec === null ? null : parseSectionPlane(spec);
  const axis: SectionAxis = plane?.axis ?? "Z";
  const sign: 1 | -1 = plane?.sign ?? 1;
  const range = axisRange(bounds, axis);
  const offset = plane?.offset ?? (range.min + range.max) / 2;

  /** Any change to the cut invalidates a rendered plate; see the header. */
  const setPlane = (nextSign: 1 | -1, nextAxis: SectionAxis, nextOffset: number): void => {
    workspaceStore.update({
      section_plane: formatSectionPlane(nextSign, nextAxis, nextOffset),
      channel_overlay: "none",
    });
  };

  if (plane === null) {
    return (
      <div className={styles["control"]} data-section-control="off">
        <button
          type="button"
          className={styles["enable"]}
          data-testid="section-enable"
          onClick={() => {
            const initial = axisRange(bounds, "Z");
            setPlane(1, "Z", (initial.min + initial.max) / 2);
          }}
        >
          {copy.viewport.section.enable}
        </button>
      </div>
    );
  }

  return (
    <div className={styles["control"]} data-section-control="on" data-section-plane={plane.spec}>
      <span className={styles["label"]}>{copy.viewport.section.label}</span>

      <select
        className={styles["axis"]}
        aria-label={copy.viewport.section.axis}
        data-testid="section-axis"
        value={axis}
        onChange={(event) => {
          const nextAxis = event.target.value as SectionAxis;
          const next = axisRange(bounds, nextAxis);
          setPlane(sign, nextAxis, (next.min + next.max) / 2);
        }}
      >
        {SECTION_AXES.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>

      <button
        type="button"
        className={styles["side"]}
        aria-label={copy.viewport.section.side}
        data-testid="section-side"
        data-section-side={sign === 1 ? "+" : "-"}
        onClick={() => {
          setPlane(sign === 1 ? -1 : 1, axis, offset);
        }}
      >
        {sign === 1 ? "+" : "−"}
        {axis}
      </button>

      <input
        className={styles["offset"]}
        type="range"
        aria-label={copy.viewport.section.offset}
        data-testid="section-offset"
        min={range.min}
        max={range.max}
        step={range.step}
        value={offset}
        onChange={(event) => {
          setPlane(sign, axis, Number(event.target.value));
        }}
      />

      <button
        type="button"
        className={styles["render"]}
        data-testid="section-render"
        disabled={overlay === "section"}
        onClick={() => {
          workspaceStore.update({ channel_overlay: "section" });
        }}
      >
        {copy.viewport.section.render}
      </button>

      <button
        type="button"
        className={styles["clear"]}
        data-testid="section-clear"
        onClick={() => {
          workspaceStore.update({ section_plane: null, channel_overlay: "none" });
        }}
      >
        {copy.viewport.section.disable}
      </button>
    </div>
  );
}
