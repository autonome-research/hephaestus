// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The STAGE (INTERFACE.md §4.1) — "geometry, with Script and Diff as *tabs over
// the same region*, so the viewport is the default and text is the deviation —
// the inverse of an IDE, on purpose. This is a CAD workspace."
//
// The tab is workspace state (`stage_tab`, §4.5) and therefore lives in the URL,
// so a link to a script view reopens on the script view.
//
// Two of the three tabs are not built here and say so by name rather than
// rendering an empty frame. §4.4's discipline is a general one: a state that
// exists for a reason reads as designed; the same state with its content missing
// reads as a bug.

import { copy } from "../../copy";
import { useWorkspace, workspaceStore } from "../../state/react";
import { STAGE_TABS, type StageTab } from "../../state/workspace";
import { useDirtyIndex } from "../rail/GitDirty";
import { ScriptEditor } from "./ScriptEditor";
import { Inspector } from "./Inspector";
import { Viewport } from "./viewport/Viewport";
import styles from "./Stage.module.css";

export function Stage(): React.JSX.Element {
  const tab = useWorkspace((s) => s.stage_tab);
  const part = useWorkspace((s) => s.part);
  const dirty = useDirtyIndex();
  // §13.1: "a dot on the Script tab", from `git status` and from nothing else.
  const partDirty = part !== null && dirty.byPart.has(part);

  return (
    <div className={styles["stage"]}>
      <div className={styles["region"]}>
        <div className={styles["tabs"]} role="tablist" aria-label={copy.app.tagline}>
          {STAGE_TABS.map((name: StageTab) => (
            <button
              key={name}
              type="button"
              role="tab"
              aria-selected={tab === name}
              className={styles["tab"]}
              data-stage-tab={name}
              onClick={() => {
                workspaceStore.update({ stage_tab: name });
              }}
            >
              {copy.stage.tabs[name]}
              {name === "script" && partDirty ? (
                <span
                  className={styles["dot"]}
                  data-dirty="worktree"
                  aria-label={copy.rail.dirtyMarkerLabel}
                >
                  ●
                </span>
              ) : null}
            </button>
          ))}
        </div>

        <div className={styles["content"]} role="tabpanel">
          {tab === "script" ? (
            <ScriptEditor />
          ) : tab === "viewport" ? (
            <Viewport />
          ) : (
            <p className={styles["absent"]}>{copy.stage.diffPending}</p>
          )}
        </div>
      </div>

      <Inspector />
    </div>
  );
}
