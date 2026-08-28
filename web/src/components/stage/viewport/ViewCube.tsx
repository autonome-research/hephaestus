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
import { STANDARD_VIEWS } from "../../../state/workspace";
import styles from "./ViewCube.module.css";

export function ViewCube(): React.JSX.Element {
  const view = useWorkspace((s) => s.view);
  const standard = (STANDARD_VIEWS as readonly string[]).includes(view);

  return (
    <div className={styles["cube"]} data-view-cube="" aria-label={copy.viewport.viewCube.label}>
      <div className={styles["grid"]} role="group" aria-label={copy.viewport.viewCube.label}>
        {STANDARD_VIEWS.map((name) => (
          <button
            key={name}
            type="button"
            className={styles["face"]}
            data-view={name}
            aria-pressed={view === name}
            onClick={() => {
              workspaceStore.update({ view: name });
            }}
          >
            {name}
          </button>
        ))}
      </div>
      {standard ? null : (
        <p className={styles["free"]} data-view-free={view} title={copy.viewport.viewCube.freeExplain}>
          {copy.viewport.viewCube.free}: <span className={styles["name"]}>{view}</span>
        </p>
      )}
    </div>
  );
}
