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

// §4.7's `Input`: the slider's numeric readout is `.data`, right-aligned, and
// **EDITABLE**. "A slider whose value cannot be typed is not a parameter
// control (§10)." The shipped readout was `t.toFixed(2)` as inert text, so a
// reader who wanted exactly 0.60 had to drag for it. The `Slider` primitive
// pairs the range with a number input over the same value.

import { useState } from "react";
import { copy } from "../../../copy";
import { useWorkspace, workspaceStore } from "../../../state/react";
import { Button, Slider } from "../../../system";
import styles from "./ExplodeSlider.module.css";

const STEP = 0.01;

export function ExplodeSlider({
  noop = false,
  yielded = false,
}: {
  /** A 1-solid sheet: explode does nothing, so the slider starts collapsed (#60). */
  readonly noop?: boolean | undefined;
  /**
   * §5.5 C18: below the 560px stage width the band yields in a fixed order and
   * the explode slider collapses to its disclosure FIRST. The disclosure still
   * opens on request; nothing about `explode_t` changes.
   */
  readonly yielded?: boolean | undefined;
}): React.JSX.Element {
  const t = useWorkspace((s) => s.explode_t);
  const [open, setOpen] = useState(false);
  const collapsed = ((noop && t === 0) || yielded) && !open;

  if (collapsed) {
    const why = noop ? copy.viewport.explode.noop : copy.viewport.explode.explain;
    return (
      <div
        className={styles["control"]}
        data-explode-t={t}
        data-explode-collapsed=""
        title={why}
      >
        <Button
          variant="quiet"
          expanded={false}
          data-explode-disclose=""
          title={why}
          onClick={() => {
            setOpen(true);
          }}
        >
          {copy.viewport.explode.disclose}
        </Button>
      </div>
    );
  }

  return (
    <div className={styles["control"]} data-explode-t={t} title={copy.viewport.explode.explain}>
      <Slider
        className={styles["slider"]}
        label={copy.viewport.explode.label}
        value={t}
        min={0}
        max={1}
        step={STEP}
        data-testid="explode-slider"
        onChange={(next) => {
          workspaceStore.update({ explode_t: next });
        }}
      />
      {t === 0 ? (
        <Button variant="quiet" disabled reason={copy.viewport.explode.resetDisabled}>
          {copy.viewport.explode.reset}
        </Button>
      ) : (
        <Button
          variant="quiet"
          data-explode-reset=""
          onClick={() => {
            workspaceStore.update({ explode_t: 0 });
          }}
        >
          {copy.viewport.explode.reset}
        </Button>
      )}
    </div>
  );
}
