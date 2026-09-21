// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Operator appearance cluster (INTERFACE.md §3.11, §5.5).
//
// §3.11 already authors the picture. This strip is the operator chrome that
// drives it: grid, wireframe, ortho, material override. It is a small cluster
// on the viewport that loads the pinned GLB — not a second inspector, and not
// a second toolbar.
//
// THE STORE IS THE AUTHORITY, the same way ExplodeSlider writes `explode_t`
// and never touches the scene. `Viewport.tsx` has one effect per flag and
// pushes it into the engine, so the canvas and the buttons cannot disagree.
//
// FIT LEFT THIS CLUSTER 2026-09-20, and with it the cluster's last exception:
// every control here is now a flag, so the component takes no props, holds no
// handler, and needs nothing from the viewport but to be drawn beside it. What
// Fit did survives — `Viewport.tsx` re-frames whenever the named view or the
// explode state changes, which is every click on the view cube. What is gone
// is re-framing WITHOUT changing view, the one case the automatic re-frame
// skips because its framing key is unchanged; after a free orbit, recovering
// the authored framing now means clicking any cube face but the current one.
//
// DEFAULTS ARE THE AUTHORED PICTURE. A strip that arrived pressed-off would
// move G4.5's control-region pixels and §3.11.2's contrast floor by existing.
// The cluster is fixed-size chrome and does not grow on a visibility toggle.
//
// No new icon id: §3.12 is closed at 18. The words live in `copy.ts`.

import { useSyncExternalStore } from "react";
import { copy } from "../../../copy";
import { appearanceStore, type AppearanceToggle } from "../../../state/appearance";
import { Button, type IconId } from "../../../system";
import styles from "./AppearanceControls.module.css";

const TOGGLE_COPY: Readonly<Record<AppearanceToggle, { label: string; explain: string }>> = {
  wireframe: copy.viewport.appearance.wireframe,
  ortho: copy.viewport.appearance.ortho,
  grid: copy.viewport.appearance.grid,
  materialOverride: copy.viewport.appearance.material,
};

/**
 * One icon per toggle (2026-09-20).
 *
 * The cluster moved into the stage's 36px rail, and a column of word-buttons
 * was wider than the model beside it. The WORD is not dropped — it is the
 * accessible name and the tooltip on every one of these; what changed is that
 * it is no longer the thing drawn.
 */
const TOGGLE_ICON: Readonly<Record<AppearanceToggle, IconId>> = {
  wireframe: "wireframe",
  ortho: "ortho",
  grid: "grid",
  materialOverride: "material",
};

/**
 * Every toggle, drawn (2026-09-20). No disclosure.
 *
 * Three of these used to sit behind a "Show view options" chevron, from when
 * they were WORDS and a row could not hold five of them. As icons in a 36px
 * column they cost 30px each, and a chevron that reveals three icons is a click
 * to save 90px of a rail that is already the narrowest thing on screen — plus
 * a second state to remember. `triad` left this list earlier the same day with
 * the axis triad itself; a toggle whose flag nothing reads is a control that
 * lies about having an effect.
 */
const TOGGLES = ["grid", "wireframe", "ortho", "materialOverride"] as const;

export function AppearanceControls(): React.JSX.Element {
  const appearance = useSyncExternalStore(
    appearanceStore.subscribe,
    appearanceStore.getSnapshot,
    appearanceStore.getSnapshot,
  );
  const toggle = (field: AppearanceToggle): React.JSX.Element => (
    <Button
      key={field}
      variant="toggle"
      icon={TOGGLE_ICON[field]}
      iconLabel={TOGGLE_COPY[field].label}
      pressed={appearance[field]}
      data-appearance-control={field}
      title={`${TOGGLE_COPY[field].label} — ${TOGGLE_COPY[field].explain}`}
      onClick={() => {
        appearanceStore.toggle(field);
      }}
    />
  );

  return (
    <div
      className={styles["cluster"]}
      data-appearance=""
      role="toolbar"
      aria-label={copy.viewport.appearance.label}
    >
      {TOGGLES.map((field) => toggle(field))}
    </div>
  );
}
