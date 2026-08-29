// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The grid readout (INTERFACE.md §5.5), bottom-left of the Stage.
//
// §5.5: "The grid readout shows camera state and scale — **a screen-space fact,
// never rendered through `<Fact>`**." §1 says the same from the other side:
// "Screen-space quantities are exempt *and are never rendered as facts*: the
// grid readout renders a camera state, never a measurement."
//
// So every number here is deliberately **not** a `<Fact>` and carries no
// `data-source`. That is the point of the clause and it is the one place in this
// app where an unattributed number is correct: attributing a camera half-height
// to an HTTP response field would be a lie, and rendering it through `<Fact>`
// would put a camera state into the e2e's DOM-vs-JSON comparison, where it has
// no counterpart to be compared against.
//
// The view **name** is not a measurement either, and it is the readout's most
// useful line: §5.5 keeps every reachable camera nameable so that what the
// screen shows can be asked of `heph render`. The name is shown so a reader can
// do that without opening the address bar.
//
// ── WHAT MOVED OUT OF HERE, AND WHY IT HAD TO ───────────────────────────────
//
// The readout used to gain a third row — "N solids hidden" — when §5.4's
// toggles hid something. Two reasons it now lives in the Results panel instead,
// beside the toggles that produce it:
//
// 1. **§5.5 says what this readout is: "camera state and scale".** A hidden
//    count is neither. It is a scene-graph fact whose control is in the Results
//    panel (§5.4, §6.1), and putting it here put a fact about the model in the
//    box that reports the camera.
//
// 2. **It broke G4.5, measurably.** `Viewport.module.css`'s own header claims
//    "a screenshot of the canvas alone (which is what §5.4's delta reads)
//    contains no chrome" — and that claim is FALSE for a Playwright element
//    screenshot, which composites whatever is painted over the element. So this
//    overlay growing a row on the toggle put chrome pixels into G4.5's control
//    region: **measured at 1.10% of 544231 control pixels against a ≤1% ceiling,
//    and 0.0000 with this row suppressed.** The delta is supposed to be about
//    the solid, and it now is.
//
// §3.3's principle 4 says the same thing from the design side: furniture does
// not move, and an overlay that changes size when the model changes is
// furniture moving.

import { copy } from "../../../copy";
import { useWorkspace } from "../../../state/react";
import styles from "./GridReadout.module.css";

export interface GridReadoutProps {
  /** The camera's half-height in model units. A screen-space quantity. */
  readonly scale: number;
  /**
   * The ground grid's spacing in model units (§3.11.5), or 0 before a framing.
   *
   * §3.11 opened by calling this component "a text box reading `View iso /
   * Scale 172 mm` **about a grid that does not exist**". The grid exists now
   * (`viewport/display.ts`), and this row is the other half of that sentence:
   * the number is read off the engine that built the grid, so the readout
   * describes the lines a reader can count rather than a second derivation of
   * the same span. `engine.gridStep()` is the one authority.
   *
   * THE ROW IS FIXED-WIDTH BY CONSTRUCTION, and that is a G4.5 constraint, not
   * a taste. This overlay grew and shrank once before — see below — and it cost
   * the gate a control region. The step changes only when the camera is
   * re-framed (a view change, explode engaging), never on a visibility toggle,
   * so no frame G4.5 compares can straddle a change to it.
   */
  readonly step: number;
}

/** Two significant figures is a readout, not a measurement; §1 forbids the latter. */
function readScale(halfHeight: number): string {
  if (!Number.isFinite(halfHeight) || halfHeight <= 0) return "—";
  const span = halfHeight * 2;
  return span >= 100 ? span.toFixed(0) : span >= 10 ? span.toFixed(1) : span.toFixed(2);
}

/**
 * The grid step, on the same reading-not-measuring rule.
 *
 * `gridStep` returns a 1-2-5 rung, so the value is exact at the precision it is
 * printed to and the trailing zeros a fixed decimal would add would be noise.
 */
function readStep(step: number): string {
  if (!Number.isFinite(step) || step <= 0) return "—";
  return step >= 1 ? String(step) : step.toFixed(step >= 0.1 ? 1 : 2);
}

export function GridReadout({ scale, step }: GridReadoutProps): React.JSX.Element {
  const view = useWorkspace((s) => s.view);
  return (
    <div className={styles["readout"]} data-grid-readout="" aria-live="off">
      <span className={styles["row"]}>
        <span className={styles["key"]}>{copy.viewport.readout.view}</span>
        <span className={styles["value"]} data-readout-view={view}>
          {view}
        </span>
      </span>
      <span className={styles["row"]}>
        <span className={styles["key"]}>{copy.viewport.readout.scale}</span>
        <span className={styles["value"]} data-readout-scale="">
          {readScale(scale)} {copy.viewport.readout.units}
        </span>
      </span>
      <span className={styles["row"]}>
        <span className={styles["key"]}>{copy.viewport.readout.grid}</span>
        <span className={styles["value"]} data-readout-grid="">
          {readStep(step)} {copy.viewport.readout.units}
        </span>
      </span>
    </div>
  );
}
