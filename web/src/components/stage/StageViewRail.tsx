// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The stage's own view rail (§4.1, amended 2026-09-20).
//
// Viewport and Diff switch what the STAGE shows, so they sit on the stage's
// trailing edge rather than in the shell's task bar — the switch is beside the
// thing it switches. Script stays in the task bar: it is the one view you leave
// the model for, and it is reached from the same column Parts is.
//
// NOT A TABLIST any more, and that is the cost of the split. A `role="tablist"`
// owns roving-tabindex navigation across its members, and members in two
// different regions cannot share one roving index — so these are plain toggles
// carrying `aria-pressed`, and the stage region below is a labelled `region`
// rather than a `tabpanel`. `[data-stage-tab]` is unchanged, so every gate that
// addresses a view by name still finds it.
//
// Icon-only by design: the rail overlays the canvas, and a column of words over
// the model is the furniture this whole pass has been removing. Each control
// keeps its name on `aria-label` and in `title`.

import { copy } from "../../copy";
import { useWorkspace, workspaceStore } from "../../state/react";
import { shellStore } from "../../state/shell";
import { effectiveInspectorTab, type StageTab } from "../../state/workspace";
import { plateOwnsWell } from "../../viewport/section";
import { Button, type IconId } from "../../system";
import { AppearanceControls } from "./viewport/AppearanceControls";
import styles from "./StageViewRail.module.css";

/** The views that live on the stage's edge, in the order they are drawn. */
const RAIL_VIEWS: readonly { readonly id: StageTab; readonly icon: IconId }[] = [
  { id: "viewport", icon: "cube" },
];

/**
 * Diff sits at the FOOT of the column (2026-09-20), under the appearance
 * flags rather than above them.
 *
 * The column reads top-to-bottom as "what am I looking at, then how am I
 * looking at it". Diff is neither: it swaps the stage for a text comparison,
 * which is a departure from the model rather than a way of viewing it — the
 * same reason Script lives in the task bar and not here. Putting it at the
 * bottom keeps the four flags adjacent to the Viewport toggle they modify,
 * and leaves the one control that leaves the model at the far end.
 */
const RAIL_FOOT: readonly { readonly id: StageTab; readonly icon: IconId }[] = [
  { id: "diff", icon: "plane" },
];

export function StageViewRail(): React.JSX.Element {
  const tab = useWorkspace((s) => s.stage_tab);
  const inspectorTab = useWorkspace((s) => s.inspector_tab);
  const panelGeometry = shellStore.getSnapshot().panelOpen.includes("results");
  const overlay = useWorkspace((s) => s.channel_overlay);
  const sectionPlane = useWorkspace((s) => s.section_plane);

  return (
    <div className={styles["rail"]} role="group" aria-label={copy.stage.viewsLabel} data-stage-rail="">
      {RAIL_VIEWS.map(({ id, icon }) => (
        <Button
          key={id}
          variant="toggle"
          icon={icon}
          iconLabel={copy.stage.tabs[id]}
          pressed={tab === id}
          title={copy.stage.tabs[id]}
          onClick={() => {
            // The inspector's own tab follows the stage's, exactly as it did
            // from the struck tab strip: choosing a view must not leave the
            // geometry list drawn twice.
            const nextInspector = effectiveInspectorTab(id, inspectorTab, panelGeometry);
            workspaceStore.update(
              nextInspector === inspectorTab
                ? { stage_tab: id }
                : { stage_tab: id, inspector_tab: nextInspector },
            );
          }}
          data-stage-tab={id}
        />
      ))}

      {/* The viewport's appearance flags dock here, below a divider, so every
          control that changes what you are LOOKING AT is one column instead of
          two corners of the canvas. `Viewport` cannot render them: the rail is
          its sibling and must outlive it, because the rail is how you get back
          from Script and Diff.

          The gate is workspace state (2026-09-20). It used to be a module store
          the viewport published to, because Fit's HANDLER had to cross that
          sibling boundary — presence never did: `Stage` mounts `Viewport` if
          and only if this same tab is `viewport`. Fit left the cluster and the
          store went with it.

          The second clause is §5.3 C19: behind a rendered section plate these
          flags drive a camera the reader is not looking at, so they unmount
          with the view cube. `Viewport` owns the cube and this rail owns the
          cluster, so the predicate lives in `viewport/section.ts` and both
          call it — one of them gaining a clause the other lacks is exactly how
          a cluster comes to be painted over a plate. */}
      {tab !== "viewport" || plateOwnsWell(overlay, sectionPlane) ? null : (
        <div className={styles["slot"]} data-appearance-slot="">
          <AppearanceControls />
        </div>
      )}

      <div className={styles["foot"]}>
        {RAIL_FOOT.map(({ id, icon }) => (
          <Button
            key={id}
            variant="toggle"
            icon={icon}
            iconLabel={copy.stage.tabs[id]}
            pressed={tab === id}
            title={copy.stage.tabs[id]}
            onClick={() => {
              const nextInspector = effectiveInspectorTab(id, inspectorTab, panelGeometry);
              workspaceStore.update(
                nextInspector === inspectorTab
                  ? { stage_tab: id }
                  : { stage_tab: id, inspector_tab: nextInspector },
              );
            }}
            data-stage-tab={id}
          />
        ))}
      </div>
    </div>
  );
}
