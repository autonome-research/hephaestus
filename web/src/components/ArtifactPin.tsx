// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The artifact pin (INTERFACE.md §12.1, §4.5), in the header.
//
// §4.1 calls the header "the most important element in the document, because
// G5.5/G5.6 are exactly the case where a user must not be able to forget which
// build they are looking at". Two behaviours discharge that:
//
// * **Never auto-advance.** The store's `observeCurrent` is a no-op while held;
//   this component is the *only* place `hold` and `followCurrent` are called,
//   and both are explicit user acts.
// * **Say what "Follow current" discards.** §4.5: the header offers it "as an
//   explicit one-click action that states what it will discard". The selection
//   and the measurement were taken against the held artifact; the copy says so
//   before the click, not after.
//
// When the pin is held, `data-pin-mode="pinned"` marks the header and every
// panel below inherits the marking through the shell's own attribute.

import { copy } from "../copy";
import { workspaceStore, useWorkspace } from "../state/react";
import { Fact } from "./Fact";
import styles from "./ArtifactPin.module.css";

export interface ArtifactPinProps {
  /** The artifact ref the server currently calls `current` for the open part. */
  readonly currentRef: string | null;
}

/** A ref is long and content-addressed; the head and tail identify it on sight. */
function abbreviate(ref: string): string {
  return ref.length <= 34 ? ref : `${ref.slice(0, 22)}…${ref.slice(-8)}`;
}

export function ArtifactPin({ currentRef }: ArtifactPinProps): React.JSX.Element {
  const ref = useWorkspace((s) => s.artifact_ref);
  const mode = useWorkspace((s) => s.pin_mode);
  const held = mode === "pinned";

  return (
    <div
      className={styles["pin"]}
      data-pin-mode={mode}
      data-testid="artifact-pin"
      title={held ? copy.header.pinnedBanner : copy.header.unpinned}
    >
      <span className={styles["label"]}>{copy.header.pin}</span>
      {ref === null ? (
        <span className={styles["absent"]}>{copy.absent.unavailable}</span>
      ) : (
        <Fact source="build.artifact_ref" value={ref} mono className={styles["ref"]}>
          {abbreviate(ref)}
        </Fact>
      )}
      <span className={styles["mode"]}>{copy.pinMode[mode]}</span>
      {held ? (
        <button
          type="button"
          className={styles["follow"]}
          title={copy.header.followCurrentExplain}
          onClick={() => {
            workspaceStore.followCurrent(currentRef);
          }}
        >
          {copy.header.followCurrent}
        </button>
      ) : (
        <button
          type="button"
          className={styles["hold"]}
          disabled={ref === null}
          title={copy.header.pinnedBanner}
          onClick={() => {
            if (ref !== null) workspaceStore.hold(ref);
          }}
        >
          {copy.pinMode.pinned}
        </button>
      )}
    </div>
  );
}
