// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The shell (INTERFACE.md §4.1): HEADER over RAIL | STAGE | STREAM.
//
// The STREAM is "a full-height peer column, collapsible but not hidden by
// default. Giving the agent a column rather than a bottom drawer is the
// 'collaborator, not console' claim cashed out in layout."
//
// §4.1's 2026-08-28 AMENDMENT, all three corrections, live here:
//
// (a) ONE BREAKPOINT AUTHORITY. `useBreakpoint()` reads the width; React writes
//     `data-stream` and `data-rail`; `Shell.module.css` keeps **no** media query
//     that changes `grid-template-columns`. The shipped arrangement had the CSS
//     collapsing the column while `useState(true)` decided whether the panel
//     rendered, and between 1024 and 1279px they disagreed and the panel shredded
//     into a one-word-per-line ribbon with the body overflowing. `state/shell.ts`
//     carries the measurement table.
//
// (b) `data-rail` IS WIRED. It was consumed by a CSS rule and set by nothing, so
//     below 1024px the rail was a 280px overlay over a third of the stage with no
//     scrim, no close control, and **no dismissal at all**. It now has all three,
//     plus focus restored to the toggle that opened it (§3.13.4).
//
// (c) The drawer's height is explicit and lives in `Stage.tsx`.
//
// §4.1 also makes the collapsed Stream **a control, not a narrower panel**:
// focusing or activating the strip expands the column, "because a composer
// cannot live in 44px" (§7A.1).

import { useEffect, useLayoutEffect, useRef } from "react";
import { useProjectRefresh } from "../api/projectRefresh";
import { useProject } from "../api/queries";
import { copy } from "../copy";
import { useWorkspace } from "../state/react";
import { shellStore } from "../state/shell";
import { Button, Icon, useBreakpoint } from "../system";
import { bindOverlayScrollTree } from "../system/overlayScroll";
import roles from "../system/type.module.css";
import { Header } from "./Header";
import { RefusalBanner } from "./RefusalBanner";
import { GitDirtyPanel } from "./rail/GitDirty";
import { ProjectTree } from "./rail/ProjectTree";
import { ProvidersPanel } from "./ProvidersPanel";
import { VersionList } from "./rail/VersionList";
import { Stage } from "./stage/Stage";
import { StreamPanel } from "./stream/StreamPanel";
import styles from "./Shell.module.css";

export function Shell(): React.JSX.Element {
  // §7A.11 lives at project lifetime, not Stream column mount (#92).
  useProjectRefresh();
  const shell = useBreakpoint();
  // §4.1: when the pin is not the current build "the header is visibly marked
  // and every panel below inherits that marking". The attribute is the
  // inheritance: any panel can style against `[data-pin-mode="pinned"] …`.
  const pinMode = useWorkspace((s) => s.pin_mode);
  // `GET /project` is the read every other panel presupposes. When *it* is
  // refused, saying which refusal it was beats N empty panels (§2.4).
  const project = useProject();
  const railRef = useRef<HTMLElement | null>(null);

  /**
   * Hand focus back to the control that opened the overlay (§3.13.4).
   *
   * Addressed through its `data-*` selector rather than a ref threaded through
   * `Header`: the toggle is rendered by `Header` and only exists in one band, so
   * a ref would have to be optional at every hop, and the attribute is the same
   * contract the e2e reads.
   */
  const focusRailToggle = (): void => {
    document.querySelector<HTMLElement>("[data-rail-toggle]")?.focus();
  };

  const railOverlayOpen = shell.railOverlay && shell.railOpen;

  // Overlay scroll cues (#115 leftover). Native thumbs are hidden globally so
  // they take no layout; this binds the 2px absolutely positioned cue on every
  // `[data-overlay-scroll]` that mounts — rail, well, Results, stage.
  useLayoutEffect(() => bindOverlayScrollTree(document), []);

  // §3.13.4: the overlay closes on Escape and hands focus back to its opener.
  // A surface that covers a third of the stage and cannot be dismissed from the
  // keyboard is the defect (b) names, said the other way round.
  useEffect(() => {
    if (!railOverlayOpen) return;
    const onKey = (event: KeyboardEvent): void => {
      if (event.key !== "Escape") return;
      shellStore.setRailOpen(false);
      focusRailToggle();
    };
    document.addEventListener("keydown", onKey);
    railRef.current?.querySelector<HTMLElement>("button, [tabindex]")?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [railOverlayOpen]);

  return (
    <div className={styles["shell"]} data-pin-mode={pinMode}>
      <nav className={styles["skip"]} aria-label={copy.skip.links}>
        <a className={roles["label"]} href="#stage" data-skip="stage">
          {copy.skip.stage}
        </a>
        <a className={roles["label"]} href="#composer" data-skip="composer">
          {copy.skip.composer}
        </a>
      </nav>
      <Header
        railToggle={
          shell.railOverlay ? (
            <Button
              variant="quiet"
              icon="sidebar"
              iconLabel={shell.railOpen ? copy.rail.close : copy.rail.open}
              onClick={() => {
                shellStore.setRailOpen(!shell.railOpen);
              }}
              data-rail-toggle=""
            />
          ) : undefined
        }
      />
      <RefusalBanner
        error={project.error}
        onRetry={() => {
          void project.refetch();
        }}
      />
      <div
        className={styles["body"]}
        data-stream={shell.streamOpen ? "open" : "collapsed"}
        data-rail={shell.railOverlay ? (shell.railOpen ? "overlay" : "hidden") : "column"}
        data-band={shell.band}
      >
        {railOverlayOpen ? (
          <div
            className={styles["scrim"]}
            data-rail-scrim=""
            onClick={() => {
              shellStore.setRailOpen(false);
            }}
          />
        ) : null}

        <nav
          ref={railRef}
          className={styles["rail"]}
          aria-label={copy.rail.title}
          data-overlay-scroll=""
        >
          {shell.railOverlay ? (
            <div className={styles["railHead"]}>
              <Button
                variant="quiet"
                icon="close"
                iconLabel={copy.rail.close}
                onClick={() => {
                  shellStore.setRailOpen(false);
                  focusRailToggle();
                }}
                data-rail-close=""
              />
            </div>
          ) : null}
          <ProjectTree />
          <GitDirtyPanel />
          <VersionList />
          {/*
            §4.2's amended panel inventory (§23): `ProvidersPanel` sits on the
            rail beside the project's other configuration, because "which model
            is attached" is a project-level fact like the working tree and the
            version list — not a property of whatever part is selected.

            §23.0's success condition is what its placement has to serve: the
            operator must be able to go from a refusing session route to a
            running turn without leaving the page, so the panel is *on* the page
            rather than behind a settings route the empty state links to.
          */}
          <ProvidersPanel />
        </nav>

        <main className={styles["stage"]}>
          <Stage />
        </main>

        <aside className={styles["stream"]} aria-label={copy.stream.title}>
          {shell.streamOpen ? (
            /* §4.1(h), amended 2026-09-02 (C25): the eyebrow band is struck AS
               A BAND. The collapse control renders as the trailing item of the
               session tab strip inside `StreamPanel`, keeping its hook and its
               `iconLabel` name; the `aside` keeps `copy.stream.title` as its
               `aria-label` above. In the steady state exactly one row of chrome
               renders above the transcript — the strip itself. */
            <StreamPanel />
          ) : (
            // §4.1: the strip is a CONTROL. Focus alone expands it, because a
            // composer cannot live in 44px and a tab stop that leads into a
            // 44px column is a trap with extra steps.
            //
            // §4.1(f), amended 2026-09-01 — repair (b): **no unread count, and
            // that is a decision rather than a gap.** The struck breakpoint
            // prose promised "a docked strip with an unread count" and nothing
            // ever built one. The clause is WITHDRAWN, not merely unbuilt: a
            // badge on a control whose only job is to stop existing on focus
            // would be a number nobody reads, and "unread" is a fact this
            // product does not have — live events are keyed `(run_id, seq)`,
            // historical ones `(session_id, ordinal)` (§2.8), and there is no
            // read watermark on either side, so a count here would be
            // client-side derived state (§1). It re-enters as §19 item 42, with
            // a server-side or explicit §4.5 workspace-state watermark, or not
            // at all. The strip renders the strip and nothing else — no count,
            // no dot, no badge (asserted in `test/shell-layout.test.ts`).
            <button
              type="button"
              className={styles["strip"]}
              aria-label={copy.stream.expand}
              aria-expanded={false}
              data-stream-strip=""
              onFocus={() => {
                shellStore.setStreamOpen(true);
              }}
              onClick={() => {
                shellStore.setStreamOpen(true);
              }}
            >
              <Icon id="sidebar" size={13} />
              <span className={styles["stripLabel"]}>{copy.stream.title}</span>
            </button>
          )}
        </aside>
      </div>
    </div>
  );
}
