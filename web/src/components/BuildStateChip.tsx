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
//   status="ok",  current=true  → current
//   status="ok",  current=false → preview
//
// **`stale` has no producer in this build and is not faked.** §5.5 defines it as
// "during a rebuild the viewport keeps the **last completed** artifact and the
// header shows `stale` with the ref it is showing" — a fact about an in-flight
// rebuild, which arrives with the viewport and the build mutation. Rendering it
// from anything available today would be inventing the state it names.

import type { BuildDocument } from "../api/types";
import { copy } from "../copy";
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

const GLYPH: Readonly<Record<BuildState, string>> = {
  current: "●",
  preview: "○",
  stale: "◑",
  failed: "✕",
  not_built: "–",
};

export function BuildStateChip({
  build,
}: {
  readonly build: BuildDocument | undefined;
}): React.JSX.Element | null {
  const state = buildState(build);
  if (state === null || build === undefined) return null;
  return (
    <span className={styles["chip"]} data-build-state={state} title={copy.header.buildState}>
      {/* §3's accessibility floor: no colour-only status encoding — the glyph
          and the word both carry the state, and the colour only reinforces it. */}
      <span aria-hidden="true" className={styles["glyph"]}>
        {GLYPH[state]}
      </span>
      <Fact source="build.status" value={build.status}>
        {copy.buildState[state]}
      </Fact>
      <Fact source="build.current" value={build.current} className={styles["hidden"]} />
    </span>
  );
}
