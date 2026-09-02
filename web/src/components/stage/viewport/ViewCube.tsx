// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The view cube (INTERFACE.md §5.5), top-right of the Stage.
//
// §5.5: "The view cube drives `view` through the `STANDARD_VIEWS` vocabulary of
// `core/render/cameras.py` plus its `az<deg>_el<deg>` grammar, so a view named
// in the UI is a view `heph render` can reproduce."
//
// It is a **list of named cameras**, not a draggable cube, and that is the
// design decision rather than a shortcut. A cube face is a picture of a name; a
// name is the thing the URL carries, the thing `heph render --view` accepts, and
// the thing a person can read back to a colleague. Free orbit is still there —
// it is the canvas, and it writes its nearest name into the same control
// (`cameras.ts::nameForDirection`), so the row below the buttons always shows
// what the current camera is called even when no button is active.
//
// The vocabulary is closed at the eight names `cameras.py` declares. There is no
// "custom" button: a camera nobody can name is a camera nobody can reproduce,
// and §5.5 exists to prevent exactly that.

import { copy } from "../../../copy";
import { useWorkspace, workspaceStore } from "../../../state/react";
import { STANDARD_VIEWS, type StandardView } from "../../../state/workspace";
import { Button } from "../../../system";
import styles from "./ViewCube.module.css";

/**
 * §4.7's 3×3 orientation cross, and the one named view on its own row.
 *
 * The VOCABULARY is closed at `cameras.py`'s eight names and is unchanged; what
 * changes is where they sit. The shipped 4×2 grid put `+Y` and `-Y` on different
 * rows and stood `front` — a named view — beside `+Z`, an axis. `null` is an
 * empty cell of the cross, not a ninth camera.
 *
 * §5.5 C19: the named-views row lives INSIDE the view-cube plate — one plate,
 * one shadow, one bounding box in the corner (`[data-view-cube]` is that box).
 */
const CROSS: readonly (StandardView | null)[] = [
  "+Y",
  "+Z",
  null,
  "-X",
  "iso",
  "+X",
  null,
  "-Z",
  "-Y",
];

/** The names that are not orientations. Kept apart because they are not one. */
const NAMED: readonly StandardView[] = ["front"];

export function ViewCube(): React.JSX.Element {
  const view = useWorkspace((s) => s.view);
  const standard = (STANDARD_VIEWS as readonly string[]).includes(view);

  const face = (name: StandardView): React.JSX.Element => (
    <Button
      key={name}
      variant="toggle"
      pressed={view === name}
      data-view={name}
      onClick={() => {
        workspaceStore.update({ view: name });
      }}
    >
      {name}
    </Button>
  );

  return (
    <div className={styles["cube"]} data-view-cube="" aria-label={copy.viewport.viewCube.label}>
      <div className={styles["cross"]} role="group" aria-label={copy.viewport.viewCube.label}>
        {CROSS.map((name, index) =>
          name === null ? <span key={`gap-${String(index)}`} /> : face(name),
        )}
      </div>
      <div className={styles["named"]} role="group" aria-label={copy.viewport.viewCube.namedLabel}>
        {NAMED.map((name) => face(name))}
      </div>
      {standard ? null : (
        <p className={styles["free"]} data-view-free={view} title={copy.viewport.viewCube.freeExplain}>
          {copy.viewport.viewCube.free}: <span className={styles["name"]}>{view}</span>
        </p>
      )}
    </div>
  );
}
