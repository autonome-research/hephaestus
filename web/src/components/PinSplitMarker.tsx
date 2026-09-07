// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §4.1's inherited marking, discharged (J-web-viewport-9).
//
// While the pin is held on one part and another is selected, the STAGE and the
// export control are showing one part's artifact and the INSPECTOR and the
// Script tab are showing another's. §4.5's amendment split those onto two axes
// deliberately; §4.1's "every panel below inherits that marking" is what makes
// the split legible, and it had no consumer at all — the shell minted an
// attribute and nothing below the header read it.
//
// Each region says WHAT IT IS SHOWING, in words, and only while the two axes
// disagree (`state/pinSplit.ts`). Words rather than a tint, because §3.13.2
// forbids colour as the sole carrier of a fact and because the two regions are
// showing two DIFFERENT things — one marking painted on both would say "unusual"
// where the reader needs "this one is the held build and that one is not".
//
// The reference is attributed on the stage marker: the stage is the region whose
// content came from the pin, and §4.6 binds a rendered value to the answer it
// came from.

import { copy } from "../copy";
import { Badge, CHIP_REF_WIDTH, formatRef } from "../system";
import type { PinSplitState } from "../state/pinSplit";
import { Fact } from "./Fact";
import styles from "./PinSplitMarker.module.css";

export interface PinSplitMarkerProps {
  readonly split: PinSplitState | null;
  /** Which axis this region follows. */
  readonly region: "stage" | "inspector";
  /** The held reference, for the stage marker's attribution. `null` elsewhere. */
  readonly artifactRef?: string | null | undefined;
}

export function PinSplitMarker({
  split,
  region,
  artifactRef,
}: PinSplitMarkerProps): React.JSX.Element | null {
  if (split === null) return null;
  const part = region === "stage" ? split.heldPart : split.selectedPart;
  return (
    <p
      className={styles["marker"]}
      data-pin-split={region}
      data-pin-split-part={part}
      // The accessible text carries BOTH part names: a screen-reader user meets
      // one region at a time and "showing bracket" alone does not say that the
      // other region is showing something else.
      aria-label={copy.header.pinSplitMarkerFull(split.heldPart, split.selectedPart)}
    >
      <Badge status="info">{copy.header.pinSplitMarkerLabel[region]}</Badge>{" "}
      <span className={styles["words"]}>
        {copy.header.pinSplitMarker[region](part)}
      </span>
      {region === "stage" && typeof artifactRef === "string" ? (
        <>
          {" "}
          <Fact
            source="workspace.artifact_ref"
            value={artifactRef}
            mono
            className={styles["ref"]}
          >
            {formatRef(artifactRef, CHIP_REF_WIDTH)}
          </Fact>
        </>
      ) : null}
    </p>
  );
}
