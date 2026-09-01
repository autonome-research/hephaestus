// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Operator appearance cluster (INTERFACE.md §3.11, §5.5).
//
// §3.11 already authors the picture. This strip is the operator chrome that
// drives it: wireframe, fit, ortho, grid, axis triad, material override. It is
// a small cluster on the viewport that loads the pinned GLB — not a second
// inspector, and not a second toolbar.
//
// THE STORE IS THE AUTHORITY, the same way ExplodeSlider writes `explode_t`
// and never touches the scene. `Viewport.tsx` has one effect per flag and
// pushes it into the engine, so the canvas and the buttons cannot disagree.
// Fit is the exception that proves the rule: it is an action, not a flag, and
// it calls the engine's existing `frame()` — `cameras.py`'s construction —
// rather than inventing a second camera.
//
// DEFAULTS ARE THE AUTHORED PICTURE. A strip that arrived pressed-off would
// move G4.5's control-region pixels and §3.11.2's contrast floor by existing.
// The cluster is fixed-size chrome and does not grow on a visibility toggle.
//
// No new icon id: §3.12 is closed at 18. The words live in `copy.ts`.

import { useState, useSyncExternalStore } from "react";
import { copy } from "../../../copy";
import { appearanceStore, type AppearanceToggle } from "../../../state/appearance";
import { Button } from "../../../system";
import styles from "./AppearanceControls.module.css";

export interface AppearanceControlsProps {
  /** False when no pinned GLB is on the canvas — Fit has nothing to frame. */
  readonly canFit: boolean;
  /** Re-apply the current named view's framing. */
  readonly onFit: () => void;
}

const TOGGLE_COPY: Readonly<Record<AppearanceToggle, { label: string; explain: string }>> = {
  wireframe: copy.viewport.appearance.wireframe,
  ortho: copy.viewport.appearance.ortho,
  grid: copy.viewport.appearance.grid,
  triad: copy.viewport.appearance.triad,
  materialOverride: copy.viewport.appearance.material,
};

/** Fit and grid stay on the stage; the rest live behind View (#60). */
const BEHIND_VIEW = ["wireframe", "ortho", "triad", "materialOverride"] as const;

function FitButton({ canFit, onFit }: AppearanceControlsProps): React.JSX.Element {
  return canFit ? (
    <Button
      variant="quiet"
      data-appearance-control="fit"
      title={copy.viewport.appearance.fit.explain}
      onClick={onFit}
    >
      {copy.viewport.appearance.fit.label}
    </Button>
  ) : (
    <Button
      variant="quiet"
      data-appearance-control="fit"
      disabled
      reason={copy.viewport.appearance.fit.disabled}
    >
      {copy.viewport.appearance.fit.label}
    </Button>
  );
}

export function AppearanceControls({ canFit, onFit }: AppearanceControlsProps): React.JSX.Element {
  const appearance = useSyncExternalStore(
    appearanceStore.subscribe,
    appearanceStore.getSnapshot,
    appearanceStore.getSnapshot,
  );
  const [moreOpen, setMoreOpen] = useState(false);

  const toggle = (field: AppearanceToggle): React.JSX.Element => (
    <Button
      key={field}
      variant="toggle"
      pressed={appearance[field]}
      data-appearance-control={field}
      title={TOGGLE_COPY[field].explain}
      onClick={() => {
        appearanceStore.toggle(field);
      }}
    >
      {TOGGLE_COPY[field].label}
    </Button>
  );

  return (
    <div
      className={styles["cluster"]}
      data-appearance=""
      role="toolbar"
      aria-label={copy.viewport.appearance.label}
    >
      <FitButton canFit={canFit} onFit={onFit} />
      {toggle("grid")}
      <Button
        variant="quiet"
        expanded={moreOpen}
        data-appearance-more=""
        title={copy.viewport.appearance.more.explain}
        onClick={() => {
          setMoreOpen((open) => !open);
        }}
      >
        {moreOpen ? copy.viewport.appearance.more.hide : copy.viewport.appearance.more.show}
      </Button>
      <div
        className={styles["more"]}
        hidden={!moreOpen}
        data-appearance-extras=""
        data-appearance-extras-open={moreOpen ? "true" : "false"}
      >
        {BEHIND_VIEW.map((field) => toggle(field))}
      </div>
    </div>
  );
}
