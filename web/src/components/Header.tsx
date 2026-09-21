// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §4.1's HEADER: `identity → pin → Export/BOM chrome`.
//
// The pin is the one dominant element. Export and BOM sit beside it as quiet
// icon-only controls (issue #12) so they do not crowd the 44px bar. The real
// workspace token is the URL fragment / sessionStorage (§2.2); the header
// does not paint a decorative Token chip. Absence is the full-page NoToken
// screen, not a header state.
//
// The two axes §13.1 insists must never blur are split across the shell on
// purpose: **the header shows the artifact axis** (the pin and the state of the
// build it names) and **the rail shows the git axis** (branch, HEAD, dirty
// markers, versions).
//
// §4.1's 2026-08-28 AMENDMENT, header half. The shipped grid was a symmetric
// three-up centring the pin, so with a short project name roughly 450px of the
// left cell and 350px of the right were dead in a 44px bar. It becomes
// `auto 1fr auto`, LEFT-ALIGNED ON ONE BASELINE, with one dominant element — the
// pin chip, carrying the ref in `.code` — and `ARTIFACT PIN` demoted from a
// printed label to a `title`.
//
// AMENDED AGAIN — the operator review of 2026-09-01, header half. Two defects,
// both measurable on the shipped bar at 1280×800:
//
// (1) **The abbreviated HEAD was not abbreviated.** `formatRef(head, 8)` fell
//     through to `slice(0, width - tail - 1)`, which for width 8 is
//     `slice(0, -1)` — the whole oid, an ellipsis, and then its own last eight
//     bytes. A 49-glyph sha in a 44px bar. `format.ts` now refuses that width
//     and `formatOid` is the prefix a git reader recognises, but the *place* was
//     wrong too: `git.branch` / `git.head` are the git axis and now sit in the
//     rail's `Working tree` panel with the rest of it (`rail/GitDirty.tsx`).
//     Nothing about the repository is reported twice.
//
// (2) **Four words for one state.** The bar stacked `unavailable` (no ref),
//     `CURRENT` (pin freshness), `held` (a disabled hold button whose label is a
//     state word) and `not built` (build state) — four labels, two vocabularies,
//     one fact: *there is nothing to look at yet*. `ArtifactPin` now renders ONE
//     badge whose word is the most specific state that is true, and the hold
//     control is a verb (`Hold`) or is not there at all.
//
// When the pin is held, `data-pin-mode="pinned"` marks the header. The pin
// is the canvas/export axis; rail selection is the inspector/script axis.
// The attribute is a marking, not a claim that every panel reports against
// the held artifact (#78).

import { useSyncExternalStore, type ReactNode } from "react";
import { useBuild, useProject } from "../api/queries";
import { copy } from "../copy";
import { useWorkspace } from "../state/react";
import { shellStore } from "../state/shell";
import { asDisplayUnit, displayUnitStore, nextUnit, unitLabel } from "../state/displayUnit";
import { Button, useShell } from "../system";
import { ArtifactPin } from "./ArtifactPin";
import { Fact } from "./Fact";
import { Logo } from "./Logo";
import { ScriptToggle } from "./ScriptToggle";
import styles from "./Header.module.css";

export interface HeaderProps {
  /** §4.1(b): the rail toggle, present only while the rail is an overlay. */
  readonly railToggle?: ReactNode | undefined;
}

export function Header({ railToggle }: HeaderProps): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  const project = useProject();
  const build = useBuild(part);
  const streamOpen = useShell().streamOpen;
  const chosen = useSyncExternalStore(
    displayUnitStore.subscribe,
    displayUnitStore.getSnapshot,
    displayUnitStore.getSnapshot,
  );
  const unit = chosen ?? asDisplayUnit(project.data?.units);

  return (
    <header className={styles["header"]}>
      <div className={styles["identity"]}>
        {railToggle ?? null}
        <Logo className={styles["mark"]} size={26} />
        {project.data === undefined ? (
          <span className={styles["absent"]}>{copy.absent.loading}</span>
        ) : (
          <Fact source="project.name" value={project.data.name} className={styles["project"]} />
        )}
      </div>

      <div
        className={styles["subject"]}
        role="group"
        aria-label={copy.header.chromeGroup}
      >
        <ArtifactPin build={build.data} />
        {/* The unit sits with the BUILD, right of Hold (2026-09-20). It was
            beside the project name, which made it read as part of the
            project's identity; it is a reading preference for the numbers in
            the panels below, and those numbers are the build's.

            It is a READOUT that is also a control: `data-source` and
            `data-value` still carry the project's OWN declaration from
            `hephaestus.toml` — that is the fact, and it does not change when
            this is clicked. What changes is the unit every length is READ in;
            see `state/displayUnit.ts` for why that is allowed to convert and
            what it refuses to touch. */}
        {project.data === undefined ? null : (
          <Fact source="project.units" value={project.data.units} className={styles["meta"]}>
            <button
              type="button"
              className={styles["unit"]}
              title={copy.header.unitCycle(unitLabel(nextUnit(unit), 1))}
              aria-label={copy.header.unitCycle(unitLabel(nextUnit(unit), 1))}
              onClick={() => {
                displayUnitStore.set(nextUnit(unit));
              }}
              data-display-unit={unit}
            >
              {unit}
            </button>
          </Fact>
        )}
        {/* Script, immediately right of the chip (2026-09-20). The chip names
            the artifact a build produced; this opens the source that produced
            it. It was the task bar's only entry — a list of one under a
            control that is not a view. */}
        <ScriptToggle />
        {/* 2026-09-20: the header's Export and BOM are STRUCK. Neither did
            anything the inspector drawer does not: BOM mounted `SourcingPanel`,
            the very component the Sourcing tab mounts, and Export ran the same
            shared submission state machine as the Export tab with a strict
            subset of its surface — no drawings, no documents, no nested-sheet
            blanks, no kerf readout, no history. Two entry points to one thing
            is two places to keep true. */}
      </div>

      {/* §4.1, amended 2026-09-20: with the Agent column closed, its reopen sits
          at the header's TRAILING edge — the corner the column comes back from
          — rather than in the task bar at the opposite side of the screen. It
          is the SAME control, not a second one: `[data-stream-toggle]` is on
          exactly one element in either state, which is what keeps a gate that
          addresses it by name unambiguous. */}
      {streamOpen ? null : (
        <div className={styles["trailing"]}>
          <Button
            variant="toggle"
            icon="compose"
            iconLabel={copy.stream.expand}
            pressed={false}
            title={copy.stream.expand}
            onClick={() => {
              shellStore.setStreamOpen(true);
            }}
            data-stream-toggle=""
          />
        </div>
      )}
    </header>
  );
}
