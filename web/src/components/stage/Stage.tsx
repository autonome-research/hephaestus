// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The STAGE (INTERFACE.md §4.1) — "geometry, with Script and Diff as *tabs over
// the same region*, so the viewport is the default and text is the deviation —
// the inverse of an IDE, on purpose. This is a CAD workspace."
//
// The tab is workspace state (`stage_tab`, §4.5) and therefore lives in the URL,
// so a link to a script view reopens on the script view. `TabBar` owns the
// `role="tablist"` contract and preserves `[data-stage-tab]` verbatim (§4.7).
//
// §4.1(c) — **THE INSPECTOR DRAWER STOPS RESIZING THE VIEWPORT.** §4.1 called
// the drawer "resizable"; the code made it *variable* — `grid-template-rows:
// minmax(0,1fr) auto` with a 132px floor — which is not the same thing, and it
// produced measured canvas heights of results 412 · properties 366 · checks 494 ·
// dfm 645 · provenance 617. A **76% swing that re-fit the 3D camera on every tab
// click.** Furniture does not move (§3.3, principle 4).
//
// The stage row is now an explicit `--drawer-height` (`clamp(200px, 32vh, 420px)`
// by default) with a 6px drag handle writing it into `state/shell.ts`; the
// drawer's own `overflow: auto` takes the excess. Height is then identical
// across tabs **by construction**, which is what §3.14's e2e asserts.
//
// Diff is still the named pending tab. Script / Timeline / Results are the
// part views: Monaco + PARAMS, the last-good scrubber, and the existing
// ResultsPanel (stage label: Geometry). When the stage tab is Results the
// inspector omits that panel so the geometry list and metrics are not drawn
// twice. The inspector tab is still named Results (§4.1, §6).

import { useCallback, useEffect, useRef } from "react";
import { copy } from "../../copy";
import { useWorkspace } from "../../state/react";
import { shellStore } from "../../state/shell";
import { EmptyState, useShell } from "../../system";
import { ResultsPanel } from "../inspector/ResultsPanel";
import { useHeldPart } from "../../state/heldPart";
import { pinSplit } from "../../state/pinSplit";
import { PinSplitMarker } from "../PinSplitMarker";
import { Inspector } from "./Inspector";
import { ScriptWorkspace } from "./ScriptWorkspace";
import { StageViewRail } from "./StageViewRail";
import { Timeline } from "./Timeline";
import { Viewport } from "./viewport/Viewport";
import styles from "./Stage.module.css";

export function Stage(): React.JSX.Element {
  const tab = useWorkspace((s) => s.stage_tab);
  const part = useWorkspace((s) => s.part);
  // §4.1's held-pin marking (J-web-viewport-9). The stage follows the PIN; the
  // inspector below follows the rail selection, and while the two disagree each
  // says which part it is showing.
  const pinMode = useWorkspace((s) => s.pin_mode);
  const artifactRef = useWorkspace((s) => s.artifact_ref);
  const heldPart = useHeldPart();
  const split = pinSplit(pinMode, heldPart, part);
  const shell = useShell();
  const hostRef = useRef<HTMLDivElement | null>(null);
  /**
   * The drag handle. Pointer capture rather than document listeners so a drag
   * that leaves the window still ends where the pointer says it ended.
   */
  const onHandleDown = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    const host = hostRef.current;
    if (host === null) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const rect = host.getBoundingClientRect();
    const move = (moveEvent: PointerEvent): void => {
      shellStore.setDrawerHeight(rect.bottom - moveEvent.clientY);
    };
    const up = (): void => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }, []);

  // The handle is keyboard-operable too (§3.13.4): a drag-only affordance is a
  // control a keyboard user cannot reach at all.
  const onHandleKey = (event: React.KeyboardEvent<HTMLDivElement>): void => {
    const current = shell.drawerHeight ?? 0;
    const host = hostRef.current;
    const fallback = host === null ? 300 : host.getBoundingClientRect().height * 0.32;
    const base = current === 0 ? Math.round(fallback) : current;
    if (event.key === "ArrowUp") shellStore.setDrawerHeight(base + 16);
    else if (event.key === "ArrowDown") shellStore.setDrawerHeight(base - 16);
    else return;
    event.preventDefault();
  };

  useEffect(() => {
    const host = hostRef.current;
    if (host === null) return;
    // The explicit height is a CSS custom property on the grid host, so the row
    // template names one value and React owns it. `null` falls back to the
    // token default rather than to a second hard-coded number.
    if (shell.drawerHeight === null) host.style.removeProperty("--drawer-height");
    else host.style.setProperty("--drawer-height", `${String(shell.drawerHeight)}px`);
  }, [shell.drawerHeight]);

  return (
    <div className={styles["stage"]} ref={hostRef}>
      <div className={styles["region"]}>
        {/* §4.1, amended 2026-09-20: the horizontal tab strip is STRUCK. The
            same closed `STAGE_TABS` vocabulary is the shell's leading column
            (`components/views/ViewsBar.tsx`), which keeps `[data-stage-tab]`
            and `tabControlId` verbatim — the region below still names its
            labelling control by id, which is valid across the DOM because the
            ids are derived rather than positional.

            Why it moved rather than shrank: the strip cost the region a full
            row for five words that were all visible at all times, and it grew
            with the vocabulary — `timeline` and `results` joined the closed set
            and the row got wider, not the region taller. A column pays for the
            vocabulary out of width the shell already owns.

            §13.1's "dot on the Script tab" moves with it, so the marking still
            sits on the control it marks. */}

        {/* §4.1's inherited marking, inside the region it marks
            (J-web-viewport-9). The container is unconditional so the region's
            three-row template does not change shape when the marker mounts;
            `PinSplitMarker` renders null unless the two axes disagree. */}
        <div data-pin-split-slot="stage">
          <PinSplitMarker split={split} region="stage" artifactRef={artifactRef} />
        </div>

        {/* §4.1, amended 2026-09-20: Viewport and Diff switch the stage, so they
            sit on the stage's own trailing edge. Script stays in the task bar.

            The region is a labelled `region`, not a `tabpanel`: its controls are
            no longer one tablist, because a roving tabindex cannot span two
            regions. `[data-stage-tab]` and the ids are unchanged. */}
        <StageViewRail />
        {/* `data-stage-view` (2026-09-20) so the stylesheet can tell a view
            the rail may FLOAT over from one it must not. Over the 3-D canvas
            an overlaid rail is correct — it is chrome on a picture, the way
            the view cube is. Over the Script editor it is occlusion: the
            rail sat on top of the PARAMS panel, which is content. */}
        <div
          className={styles["content"]}
          role="region"
          id="stage-panel"
          aria-label={copy.stage.tabsLabel}
          data-stage-view={tab}
          data-overlay-scroll=""
        >
          {tab === "script" ? (
            <ScriptWorkspace />
          ) : tab === "viewport" ? (
            <Viewport />
          ) : tab === "timeline" ? (
            <Timeline />
          ) : tab === "results" ? (
            <div data-stage-panel="results">
              <ResultsPanel />
            </div>
          ) : (
            <EmptyState
              icon="file"
              title={copy.stage.diffPendingTitle}
              body={copy.stage.diffPending}
            />
          )}
        </div>
      </div>

      {/* §4.1(c)'s 6px handle. `separator` with an orientation is the role a
          resize grip carries; the value is a pixel height, so no min/max is
          announced that the clamp would then contradict. */}
      {/* Unmounted with the drawer's body (2026-09-20): a resize grip for a
          drawer that has no body to resize is a control that does nothing,
          and it would hold a focus stop in the tab order while doing it. */}
      {!shell.drawerOpen ? null : (
        <div
          className={styles["handle"]}
          role="separator"
          aria-orientation="horizontal"
          aria-label={copy.inspector.resize}
          tabIndex={0}
          data-drawer-handle=""
          onPointerDown={onHandleDown}
          onKeyDown={onHandleKey}
        />
      )}

      <Inspector />
    </div>
  );
}
