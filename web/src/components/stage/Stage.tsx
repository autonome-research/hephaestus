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
import { useWorkspace, workspaceStore } from "../../state/react";
import { shellStore } from "../../state/shell";
import { effectiveInspectorTab, STAGE_TABS, type StageTab } from "../../state/workspace";
import { Badge, EmptyState, TabBar, tabControlId, useShell } from "../../system";
import { ResultsPanel } from "../inspector/ResultsPanel";
import { dirtySideWord, useDirtyIndex } from "../rail/GitDirty";
import { Inspector } from "./Inspector";
import { ScriptWorkspace } from "./ScriptWorkspace";
import { Timeline } from "./Timeline";
import { Viewport } from "./viewport/Viewport";
import styles from "./Stage.module.css";

export function Stage(): React.JSX.Element {
  const tab = useWorkspace((s) => s.stage_tab);
  const inspectorTab = useWorkspace((s) => s.inspector_tab);
  const part = useWorkspace((s) => s.part);
  const dirty = useDirtyIndex();
  const shell = useShell();
  const hostRef = useRef<HTMLDivElement | null>(null);
  // §13.1: "a dot on the Script tab", from `git status` and from nothing else.
  const partDirty = part !== null ? dirty.byPart.get(part) : undefined;
  const scriptDirtyWord = partDirty === undefined ? null : dirtySideWord(partDirty);

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
        <TabBar
          attr="data-stage-tab"
          panelId="stage-panel"
          label={copy.stage.tabsLabel}
          selected={tab}
          onSelect={(next: StageTab) => {
            const nextInspector = effectiveInspectorTab(next, inspectorTab);
            workspaceStore.update(
              nextInspector === inspectorTab
                ? { stage_tab: next }
                : { stage_tab: next, inspector_tab: nextInspector },
            );
          }}
          tabs={STAGE_TABS.map((name) => ({
            id: name,
            label: copy.stage.tabs[name],
            ...(name === "script" && scriptDirtyWord !== null
              ? {
                  trailing: (
                    <Badge status="dirty" title={scriptDirtyWord}>
                      {scriptDirtyWord}
                    </Badge>
                  ),
                }
              : {}),
          }))}
        />

        <div
          className={styles["content"]}
          role="tabpanel"
          id="stage-panel"
          aria-labelledby={tabControlId("data-stage-tab", tab)}
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

      <Inspector />
    </div>
  );
}
