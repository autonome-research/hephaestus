// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The artifact pin (INTERFACE.md §12.1, §4.5), in the header.
//
// §4.1 calls the header "the most important element in the document, because
// G5.5/G5.6 are exactly the case where a user must not be able to forget which
// build they are looking at". Two behaviours discharge that:
//
// * **Never auto-advance.** The store's `observeCurrent` is a no-op while held.
//   `hold` / `followCurrent` are explicit user acts: this pin, and the Timeline
//   scrubber rewinding to `error.last_good_artifact_ref`.
// * **Say what "Follow current" discards.** §4.5: the header offers it "as an
//   explicit one-click action that states what it will discard". The selection
//   and the measurement were taken against the held artifact; the copy says so
//   before the click, not after.
//
// §4.1's AMENDMENT: the pin chip is the header's ONE DOMINANT ELEMENT and its
// dominant content is **the ref, in `.code`** — the printed `ARTIFACT PIN` label
// is demoted to a `title`, because a label repeated on every load says less than
// the value it labels.
//
// §4.1's SECOND AMENDMENT (operator review, 2026-09-01) — **ONE CHIP, ONE
// WORD.** The shipped chip printed the pin vocabulary (`current` / `held`) and
// the build-state chip printed its own (`up to date` / `preview` / `not built`)
// ~600px apart, and on an unbuilt part the bar carried FOUR labels for one fact:
// `unavailable`, `CURRENT`, a disabled hold button reading `held`, and
// `not built`. Two axes are still two facts, but they are not two facts *at the
// same time*, so the chip prints the most specific state that is true:
//
//   no ref                 → the build state (`not built` / `failed`), and NO
//                            hold control, because there is nothing to hold and
//                            a disabled button labelled with a state word reads
//                            as a fifth label rather than as a control
//   held                   → `held`, plus `Follow current`
//   following, with a ref  → the build state of the build being followed
//
// Both `data-pin-mode` and `data-build-state` stay on the chip, and
// `build.status` / `build.current` / `build.artifact_ref` keep their `<Fact>`
// attribution, so the DOM contract the e2e reads is unchanged by the collapse.
//
// THAT LAST SENTENCE WAS A LIE FOR ONE STATE, and it is worth naming because it
// is the state the whole chip exists for. The first cut of this collapse chose
// between the `held` word and `BuildStateBadge` with a ternary, so while held the
// badge never mounted — and `build.status` and `build.current` went with it. The
// pin's own §4.1 quote says a held artifact is "exactly the case where a user
// must not be able to forget which build they are looking at", so unmounting the
// two fields that say which build it is, on that path alone, is the collapse
// eating the fact it was supposed to be clarifying. The badge is now mounted
// whenever there is a build document and takes `clipped` while held: one visible
// word, both fields attributed. `data-build-state` stays on this chip and is not
// re-minted on the badge.

import type { BuildDocument } from "../api/types";
import { copy } from "../copy";
import { workspaceStore, useWorkspace } from "../state/react";
import { Button, CHIP_REF_WIDTH, formatRef } from "../system";
import { BuildStateBadge, buildState } from "./BuildStateChip";
import { Fact } from "./Fact";
import styles from "./ArtifactPin.module.css";

export interface ArtifactPinProps {
  /** The open part's build, whose `artifact_ref` is what the server calls current. */
  readonly build: BuildDocument | undefined;
}

export function ArtifactPin({ build }: ArtifactPinProps): React.JSX.Element {
  const ref = useWorkspace((s) => s.artifact_ref);
  const mode = useWorkspace((s) => s.pin_mode);
  const held = mode === "pinned";
  const currentRef = build?.artifact_ref ?? null;
  const state = buildState(build);

  return (
    <div
      className={styles["pin"]}
      data-pin-mode={mode}
      data-testid="artifact-pin"
      {...(state === null ? {} : { "data-build-state": state })}
      title={
        ref === null
          ? held
            ? copy.header.pinnedBanner
            : copy.header.unpinned
          : `${ref}. ${held ? copy.header.pinnedBanner : copy.header.unpinned}`
      }
    >
      {ref === null ? null : (
        <Fact source="build.artifact_ref" value={ref} className={styles["ref"]}>
          {formatRef(ref, CHIP_REF_WIDTH)}
        </Fact>
      )}
      {/* The one VISIBLE word. `held` is the pin axis and outranks the build
          state while it is true — a held artifact is the state §4.1 says the
          operator must not be able to forget — and every other case is the
          build's own. */}
      {held ? (
        <span className={styles["mode"]} data-pin-state="held">
          {copy.pinMode.pinned}
        </span>
      ) : null}
      {/* The badge is mounted whenever the server gave us a build, INCLUDING
          while held — `clipped` drops the drawn badge and keeps `build.status`
          and `build.current` as 1px facts. Skipping the component entirely on
          the held path is what the first cut of this chip did, and it unmounted
          both fields on exactly the G5.5/G5.6 path they exist for. */}
      {state !== null ? (
        <BuildStateBadge build={build} clipped={held} />
      ) : ref === null && !held ? (
        // No ref, no build document, and not held: the workspace has nothing to
        // report about an artifact, and says which kind of nothing that is.
        <span className={styles["absent"]}>{copy.absent.unavailable}</span>
      ) : null}
      {held ? (
        <Button
          variant="secondary"
          title={copy.header.followCurrentExplain}
          onClick={() => {
            workspaceStore.followCurrent(currentRef);
          }}
          data-pin-action="follow"
        >
          {copy.header.followCurrent}
        </Button>
      ) : ref === null ? null : (
        <Button
          variant="secondary"
          title={copy.header.pinnedBanner}
          onClick={() => {
            workspaceStore.hold(ref);
          }}
          data-pin-action="hold"
        >
          {copy.header.hold}
        </Button>
      )}
    </div>
  );
}
