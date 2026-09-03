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

import { useState } from "react";
import { copy } from "../../../copy";
import { useWorkspace, workspaceStore } from "../../../state/react";
import { Button, Select, Slider } from "../../../system";
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
  /**
   * §5.5 C18: below its derived step of the band's yield ladder the section
   * control folds to a disclosure — AFTER the explode slider, before the
   * legend. The cut itself (`section_plane`, `channel_overlay`) is untouched.
   */
  readonly yielded?: boolean | undefined;
  /**
   * A simple plate: section starts collapsed so it does not crowd the band
   * (#113). The enable control is one click behind the disclosure.
   */
  readonly noop?: boolean | undefined;
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

export function SectionControl({
  bounds,
  yielded = false,
  noop = false,
}: SectionControlProps): React.JSX.Element | null {
  const spec = useWorkspace((s) => s.section_plane);
  const overlay = useWorkspace((s) => s.channel_overlay);
  /** The C18 disclosure's own open state — a person may still want the row. */
  const [open, setOpen] = useState(false);
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
    // #113 leftover: a one-solid plate does not greet the operator with
    // section chrome. Hide while there is no cut. An engaged plane stays
    // mounted so the cut can be cleared.
    if (noop && !open) return null;
    if (yielded && !open) {
      return (
        <div className={styles["control"]} data-section-control="off" data-section-collapsed="">
          <Button
            variant="quiet"
            expanded={false}
            data-section-disclose=""
            title={copy.viewport.section.disclose}
            onClick={() => {
              setOpen(true);
            }}
          >
            {copy.viewport.section.disclose}
          </Button>
        </div>
      );
    }
    return (
      <div className={styles["control"]} data-section-control="off">
        <Button
          variant="secondary"
          icon="plane"
          data-testid="section-enable"
          onClick={() => {
            const initial = axisRange(bounds, "Z");
            setPlane(1, "Z", (initial.min + initial.max) / 2);
          }}
        >
          {copy.viewport.section.enable}
        </Button>
      </div>
    );
  }

  if (yielded && !open) {
    // §5.5 C18: the band yields the CONTROL, never the cut — the plane spec
    // stays on the attribute and the workspace state is untouched.
    return (
      <div
        className={styles["control"]}
        data-section-control="on"
        data-section-plane={plane.spec}
        data-section-yielded=""
        title={copy.viewport.section.yielded}
      >
        <Button
          variant="quiet"
          expanded={false}
          data-section-disclose=""
          title={copy.viewport.section.yielded}
          onClick={() => {
            setOpen(true);
          }}
        >
          {copy.viewport.section.disclose}
        </Button>
      </div>
    );
  }

  return (
    <div className={styles["control"]} data-section-control="on" data-section-plane={plane.spec}>
      <span className={styles["label"]}>{copy.viewport.section.label}</span>

      <Select
        label={copy.viewport.section.axis}
        hideLabel
        data-testid="section-axis"
        value={axis}
        options={SECTION_AXES}
        onChange={(raw) => {
          const nextAxis = raw as SectionAxis;
          const next = axisRange(bounds, nextAxis);
          setPlane(sign, nextAxis, (next.min + next.max) / 2);
        }}
      />

      <Button
        variant="secondary"
        iconLabel={copy.viewport.section.side}
        title={copy.viewport.section.side}
        data-testid="section-side"
        data-section-side={sign === 1 ? "+" : "-"}
        onClick={() => {
          setPlane(sign === 1 ? -1 : 1, axis, offset);
        }}
      >
        {sign === 1 ? `+${axis}` : `−${axis}`}
      </Button>

      <Slider
        className={styles["offset"]}
        label={copy.viewport.section.offset}
        hideLabel
        data-testid="section-offset"
        min={range.min}
        max={range.max}
        step={range.step}
        value={offset}
        precision={2}
        onChange={(next) => {
          setPlane(sign, axis, next);
        }}
      />

      {overlay === "section" ? (
        <Button variant="primary" disabled reason={copy.viewport.section.renderDisabled}>
          {copy.viewport.section.render}
        </Button>
      ) : (
        <Button
          variant="primary"
          data-testid="section-render"
          onClick={() => {
            workspaceStore.update({ channel_overlay: "section" });
          }}
        >
          {copy.viewport.section.render}
        </Button>
      )}

      <Button
        variant="quiet"
        icon="close"
        data-testid="section-clear"
        onClick={() => {
          workspaceStore.update({ section_plane: null, channel_overlay: "none" });
        }}
      >
        {copy.viewport.section.disable}
      </Button>
    </div>
  );
}
