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

export function BuildStateChip({
  build,
}: {
  readonly build: BuildDocument | undefined;
}): React.JSX.Element | null {
  const state = buildState(build);
  if (state === null || build === undefined) return null;
  return (
    <span className={styles["wrap"]} data-build-state={state} title={copy.header.buildState}>
      <Badge status={BADGE[state]}>
        <Fact source="build.status" value={build.status}>
          {copy.buildState[state]}
        </Fact>
      </Badge>
      <Fact source="build.current" value={build.current} className={styles["hidden"]} />
    </span>
  );
}
