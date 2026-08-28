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

import { copy } from "../../../copy";
import { useWorkspace } from "../../../state/react";
import styles from "./GridReadout.module.css";

export interface GridReadoutProps {
  /** The camera's half-height in model units. A screen-space quantity. */
  readonly scale: number;
  /** How many solids the viewer has hidden — client state, not a server count. */
  readonly hiddenCount: number;
}

/** Two significant figures is a readout, not a measurement; §1 forbids the latter. */
function readScale(halfHeight: number): string {
  if (!Number.isFinite(halfHeight) || halfHeight <= 0) return "—";
  const span = halfHeight * 2;
  return span >= 100 ? span.toFixed(0) : span >= 10 ? span.toFixed(1) : span.toFixed(2);
}

export function GridReadout({ scale, hiddenCount }: GridReadoutProps): React.JSX.Element {
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
      {hiddenCount === 0 ? null : (
        <span className={styles["row"]} data-readout-hidden={hiddenCount}>
          <span className={styles["value"]}>{copy.viewport.readout.hidden(hiddenCount)}</span>
        </span>
      )}
    </div>
  );
}
