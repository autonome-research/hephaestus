// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The VIEWS BAR — the shell's leading column (§4.1, amended 2026-09-20).
//
// §4.1 put Script and Diff "as *tabs over the same region*, so the viewport is
// the default and text is the deviation". That ordering is unchanged; what
// changed is where the switch lives. A horizontal strip spent a full row of the
// stage on five words, every one of which was visible at all times, and it grew
// with the vocabulary: `timeline` and `results` joined the closed set and the
// row got wider, not the region taller.
//
// The bar is a column instead, so the stage keeps its height, and the five
// entries are the SAME closed `STAGE_TABS` vocabulary with the same
// `[data-stage-tab]` hook and the same `tabControlId` ids. Nothing about the
// contract moved — `Stage`'s region still names its labelling control through
// `aria-labelledby`, which is valid across the DOM because the ids are derived
// rather than positional.
//
// ONE WIDTH, NO CHEVRON (2026-09-20). The bar is a 44px icon rail and has no
// expanded state to toggle into: three entries with short names did not earn
// 168px of every screen, and a control whose only job is to reclaim width the
// bar should not have taken is furniture twice over. Every entry keeps its name
// on `aria-label` and in `title`, so nothing is unlabelled — the word is simply
// not drawn.

import { copy } from "../../copy";
import { shellStore } from "../../state/shell";
import { Button, useShell } from "../../system";
import styles from "./ViewsBar.module.css";

/**
 * The stage's own views (2026-09-20).
 *
 * `timeline` and `results` are NOT here: they expand in the side panel, beside
 * the model rather than instead of it. `viewport` and `diff` are not here
 * either, since 2026-09-20 — they switch the stage, so they sit on the stage's
 * own trailing edge (`stage/StageViewRail.tsx`). Script remains: it is the one
 * view you leave the model for, and it is reached from the column Parts is in.
 *
 * All five stay in `STAGE_TABS` and the stage still renders whichever a URL
 * names, so `?tab=timeline` from before these changes still opens. What moved
 * is where a CLICK puts them.
 */

export function ViewsBar(): React.JSX.Element {
  const shell = useShell();
  const railOpen = shell.railOpen;

  return (
    <nav
      className={styles["views"]}
      aria-label={copy.stage.viewsLabel}
      data-views-bar="collapsed"
    >
      {/* The side panel's toggle, as a hamburger — three bars, the one shape
          every operator already reads as "the panel of things".

          It is NOT a stage view, so it is not a tab: it toggles a column
          rather than selecting what the region below shows, and putting it in
          the tablist would make the roving-tabindex arrows walk from a view
          onto a switch. It sits above the list, as a pressed-state toggle, and
          carries the SAME hook the narrow header's control carries so a gate
          that addressed Parts by name still finds it. */}
      {/* Only while the panel is CLOSED. Open, the same control lives in the
          panel's top-right corner (`Shell.tsx`) — the control sits with the
          thing it acts on, and two `[data-rail-toggle]` elements at once is
          the duplicate-hook defect. */}
      {railOpen ? null : (
      <Button
        variant="toggle"
        icon="menu"
        iconLabel={railOpen ? copy.rail.close : copy.rail.open}
        pressed={railOpen}
        expanded={railOpen}
        className={styles["rowToggle"]}
        title={railOpen ? copy.rail.close : copy.rail.open}
        onClick={() => {
          shellStore.setRailOpen(!railOpen);
        }}
        data-rail-toggle=""
      >
        {undefined}
      </Button>
      )}

      {/* SCRIPT LEFT THIS BAR (2026-09-20) for the header, beside the build
          chip — see `components/ScriptToggle.tsx`. It was the only entry left
          here, which made this a tablist of one under a hamburger that is not
          a view: a roving-tabindex list with nothing to rove to. The bar is
          now the panel toggle alone.

          The dirty marking (§13.1) went with it. A marking left behind on a
          control nobody sees is a marking nobody sees. */}

      {/* Geometry and Timeline have NO entry here (2026-09-20). They are
          disclosures under Parts in the side panel — one control each, where
          the thing it opens actually appears. A task-bar button plus a panel
          row is two controls for one section, and the operator has to learn
          which one they are looking at. */}

      {/* The Agent column has NO entry here (2026-09-20). Its two edge
          controls live on the column itself: the `X` at the trailing end of the
          session strip closes it, and the header's trailing corner reopens it.
          A third control in a third place, for a column that is either drawn or
          not, is one more thing to find. */}

      {/* Geometry and Timeline have NO entry here (2026-09-20). They are
          disclosures under Parts in the side panel — one control each, where
          the thing it opens actually appears. A task-bar button plus a panel
          row is two controls for one section, and the operator has to learn
          which one they are looking at. */}

      {/* Geometry and Timeline have NO entry here (2026-09-20). They are
          disclosures under Parts in the side panel — one control each, where
          the thing it opens actually appears. A task-bar button plus a panel
          row is two controls for one section, and the operator has to learn
          which one they are looking at. */}


    </nav>
  );
}
