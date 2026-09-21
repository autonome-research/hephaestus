// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The Script view's control (§4.1), in the header beside the build chip.
//
// WHY IT IS HERE AND NOT IN THE TASK BAR (2026-09-20). Script was the task
// bar's only remaining entry, sitting under a hamburger that toggles a panel —
// a list of one, in a column whose other control is not a view at all. Beside
// the build chip it sits next to the thing it is about: the chip names the
// artifact a build produced, and this opens the source that produced it.
//
// NOT A TABLIST, for the reason the stage rail is not one. `role="tablist"`
// owns roving-tabindex navigation ACROSS its members, and a list with one
// member has nothing to rove to — it just costs the operator an arrow key that
// does nothing. A plain `aria-pressed` toggle says the same thing.
// `[data-stage-tab="script"]` is unchanged, so every gate that addresses the
// view by name still finds it.

import { copy } from "../copy";
import { useWorkspace, workspaceStore } from "../state/react";
import { effectiveInspectorTab } from "../state/workspace";
import { useDirtyIndex, dirtySideWord } from "./rail/GitDirty";
import { Badge, Button, useShell } from "../system";
import styles from "./ScriptToggle.module.css";

export function ScriptToggle(): React.JSX.Element {
  const tab = useWorkspace((s) => s.stage_tab);
  const inspectorTab = useWorkspace((s) => s.inspector_tab);
  const part = useWorkspace((s) => s.part);
  const panelGeometry = useShell().panelOpen.includes("results");
  // §13.1: "a dot on the Script tab", from `git status` and from nothing else.
  // It travels with the control it marks; a marking left on a struck strip is
  // a marking nobody sees.
  const dirty = useDirtyIndex();
  const partDirty = part !== null ? dirty.byPart.get(part) : undefined;
  const dirtyWord = partDirty === undefined ? null : dirtySideWord(partDirty);
  const open = tab === "script";

  return (
    <span className={styles["slot"]}>
      <Button
        variant="toggle"
        icon="code"
        iconLabel={copy.stage.tabs.script}
        pressed={open}
        title={copy.stage.tabs.script}
        onClick={() => {
          // The inspector's own tab follows the stage's, exactly as it did
          // from the task bar: choosing a view must not leave the geometry
          // list drawn twice (§4.1, #17).
          const next = effectiveInspectorTab("script", inspectorTab, panelGeometry);
          workspaceStore.update(
            next === inspectorTab
              ? { stage_tab: "script" }
              : { stage_tab: "script", inspector_tab: next },
          );
        }}
        data-stage-tab="script"
      />
      {dirtyWord === null ? null : (
        // The dot, not the sentence. §13.1 asks for a marking here; the word is
        // the badge's accessible text and the rail carries the full statement.
        <Badge status="dirty" title={dirtyWord}>
          <span className={styles["srOnly"]}>{dirtyWord}</span>
        </Badge>
      )}
    </span>
  );
}
