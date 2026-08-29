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

import { useEffect, useRef } from "react";
import { useProject } from "../api/queries";
import { copy } from "../copy";
import { useWorkspace } from "../state/react";
import { shellStore } from "../state/shell";
import { Button, Icon, useBreakpoint } from "../system";
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

        <nav ref={railRef} className={styles["rail"]} aria-label={copy.rail.title}>
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
            <>
              <div className={styles["streamHeader"]}>
                <span className={styles["streamTitle"]}>{copy.stream.title}</span>
                <Button
                  variant="quiet"
                  icon="chevron-right"
                  iconLabel={copy.stream.collapse}
                  onClick={() => {
                    shellStore.setStreamOpen(false);
                  }}
                  data-stream-collapse=""
                />
              </div>
              <StreamPanel />
            </>
          ) : (
            // §4.1: the strip is a CONTROL. Focus alone expands it, because a
            // composer cannot live in 44px and a tab stop that leads into a
            // 44px column is a trap with extra steps.
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
