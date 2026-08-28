// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The explode slider (INTERFACE.md §5.2).
//
// "The slider drives `explode_t ∈ [0,1]`; the client translates each solid's
// node by `explode_offset · t`."
//
// The slider's whole job is to write one number into workspace state. It does
// **not** touch the scene: `Viewport.tsx` has one effect per workspace field and
// pushes `explode_t` into the engine, so the URL and the canvas cannot disagree
// about how far the assembly is exploded. That indirection is what makes
// `?t=0.6` reproduce the picture on reload.
//
// The displayed `t` is **not** a `<Fact>`. It is neither a server value nor a
// measurement — it is the position of this control, a screen-space quantity §1
// exempts by name. `data-explode-t` carries it for the harness, which reads
// centroid distances out of the scene graph rather than any number rendered here
// (G4.6, §5.2).

import { copy } from "../../../copy";
import { useWorkspace, workspaceStore } from "../../../state/react";
import styles from "./ExplodeSlider.module.css";

const STEP = 0.01;

export function ExplodeSlider(): React.JSX.Element {
  const t = useWorkspace((s) => s.explode_t);

  return (
    <div className={styles["control"]} data-explode-t={t} title={copy.viewport.explode.explain}>
      <label className={styles["label"]} htmlFor="explode-t">
        {copy.viewport.explode.label}
      </label>
      <input
        id="explode-t"
        className={styles["slider"]}
        type="range"
        min={0}
        max={1}
        step={STEP}
        value={t}
        data-testid="explode-slider"
        onChange={(event) => {
          workspaceStore.update({ explode_t: Number(event.target.value) });
        }}
      />
      <span className={styles["value"]}>{t.toFixed(2)}</span>
      <button
        type="button"
        className={styles["reset"]}
        disabled={t === 0}
        onClick={() => {
          workspaceStore.update({ explode_t: 0 });
        }}
      >
        {copy.viewport.explode.reset}
      </button>
    </div>
  );
}
