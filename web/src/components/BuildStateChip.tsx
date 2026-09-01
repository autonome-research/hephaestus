// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The §4.1 header build-state chip.
//
// §4.1: the header carries "the **artifact pin** (§12.1) and the **build-state
// chip** (`current` / `preview` / `stale` / `failed`)". The vocabulary is closed
// and the chip is a *rendering of two server fields* — `build.status` and
// `build.current` — never a client verdict: §1's closed list of what the client
// must not compute names "dirty/history/publication state" explicitly, and
// whether a build is current is publication state.
//
// Both fields carry their own `data-source`, so the e2e can compare the chip
// against the JSON without parsing the word. The word itself is a label over the
// closed pair, and the mapping is total:
//
//   status="not_built"          → not built
//   status="error"              → failed
//   status="ok",  current=true  → up to date
//   status="ok",  current=false → preview
//
// **`stale` has no producer in this build and is not faked.** §5.5 defines it as
// "during a rebuild the viewport keeps the **last completed** artifact and the
// header shows `stale` with the ref it is showing" — a fact about an in-flight
// rebuild, which arrives with the viewport and the build mutation. Rendering it
// from anything available today would be inventing the state it names.
//
// §4.1's COPY DEFECT, fixed: `current` reads **"up to date"** here. The pin's
// own vocabulary keeps "current". Two axes ~600px apart, two words.
//
// The chip is a `<Badge>` (§4.7), so the glyph and the fill come from the system
// layer and the state cannot be encoded by colour alone.
//
// §4.1's SECOND AMENDMENT (operator review, 2026-09-01). This badge no longer
// occupies its own cell at the right edge of the bar: it renders INSIDE the pin
// chip, which is the element the state is about. Two chips ~600px apart, each
// carrying one word of a two-word verdict, is what let an unbuilt part print
// four labels for one fact — see `ArtifactPin.tsx`. The mapping, the vocabulary
// and the two `<Fact>` attributions below are unchanged; only the place is.

import type { BuildDocument } from "../api/types";
import { copy } from "../copy";
import { Badge, type BadgeStatus } from "../system";
import { Fact } from "./Fact";
import styles from "./BuildStateChip.module.css";

/** §4.1's closed chip vocabulary, plus the engine's own `not_built`. */
export type BuildState = "current" | "preview" | "stale" | "failed" | "not_built";

export function buildState(build: BuildDocument | undefined): BuildState | null {
  if (build === undefined) return null;
  if (build.status === "not_built") return "not_built";
  if (build.status === "error") return "failed";
  return build.current ? "current" : "preview";
}

/**
 * §4.1's five build states onto §4.7's six-value badge vocabulary.
 *
 * The two vocabularies are different closed lists about different things, and
 * this is the one place they meet. `stale` and `not_built` both land on
 * `not_run` — an absence rather than a verdict — and take their distinctness
 * from the word beside the icon, which is exactly §3.13.2's requirement.
 */
const BADGE: Readonly<Record<BuildState, BadgeStatus>> = {
  current: "pass",
  preview: "info",
  stale: "error",
  failed: "fail",
  not_built: "not_run",
};

export function BuildStateBadge({
  build,
  clipped = false,
}: {
  readonly build: BuildDocument | undefined;
  /**
   * Mount the two build fields without drawing the badge.
   *
   * The held pin prints its OWN word (`ArtifactPin`), and two state words in one
   * chip is the defect §4.1's amendment closed. But `build.status` and
   * `build.current` are facts about the build the operator is looking at, and
   * G5.5/G5.6 — a held artifact — is precisely the path where they must be
   * readable. Unmounting them there would make the amendment's claim that they
   * stay false exactly where it matters most.
   *
   * So the fields stay and the badge does not. The two `<Fact>`s carry `.hidden`
   * INDIVIDUALLY rather than the wrap carrying it around a whole badge: a
   * clipped node has to be a leaf. `overflow: hidden` on a 1px box clips what is
   * *painted*, not the layout of what is inside it, so a `Badge` under a clipped
   * wrap would still report a full-width box to anything measuring the document
   * — including §3.13.1's contrast sweep, which skips a box only when it is 2px
   * or smaller. This is the same 1px leaf `build.current` has always used.
   */
  readonly clipped?: boolean | undefined;
}): React.JSX.Element | null {
  const state = buildState(build);
  if (state === null || build === undefined) return null;
  if (clipped) {
    return (
      <span className={styles["wrap"]}>
        <Fact source="build.status" value={build.status} className={styles["hidden"]} silent />
        <Fact source="build.current" value={build.current} className={styles["hidden"]} silent />
      </span>
    );
  }
  return (
    <span className={styles["wrap"]} title={copy.header.buildState}>
      <Badge status={BADGE[state]}>
        <Fact source="build.status" value={build.status}>
          {copy.buildState[state]}
        </Fact>
      </Badge>
      <Fact source="build.current" value={build.current} className={styles["hidden"]} silent />
    </span>
  );
}
