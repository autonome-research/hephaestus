// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The INSPECTOR drawer (INTERFACE.md §4.1) — the closed inspector tabs, as a
// bottom drawer of the Stage rather than a third column.
//
// §4.1: "INSPECTOR is a bottom drawer of the Stage rather than a third column:
// its content is *about the thing in the Stage*, and losing that spatial
// relation costs more than the vertical pixels."
//
// The tab is workspace state (`inspector_tab`, §4.5), so the drawer's selection
// is in the URL and survives a reload like everything else. Each panel is a
// projection of one read route and owns its own named absences (§6.1–§6.4,
// §4.4). Sourcing reads the same properties route as Properties, filtered to
// the declared manufacturing-identity fields. When the stage tab is Results
// the Results inspector tab is omitted so the same list is not drawn twice.
//
// The sixth is §22.7's `export`, and it is the only one containing a control that
// WRITES. Issue #12 also puts a compact Export control in header chrome, bound
// to the same pin; this tab keeps history, drawings, and documents.
//
// The seventh is sourcing: BOM from declared manufacturing fields only.
//
// §4.1(c): the drawer's HEIGHT is not this component's any more — the Stage owns
// it as an explicit grid row, and `.content { overflow: auto }` takes the excess.
// The shipped `min-height: 132px` let the drawer grow with whichever panel was
// open, which is what produced the 76% canvas-height swing across tabs.
//
// `TabBar` owns the roving-tabindex contract and preserves `[data-inspector-tab]`
// verbatim (§4.7, §3.14's migration criterion).
//
// ONE PIECE OF STATE LIVES HERE AND NOWHERE ELSE: the descriptor a reader
// clicked in the DFM panel. It is deliberately not workspace state: §4.5's record
// is closed, its `selection` field is a resolved server selection, and a clicked
// descriptor is not one. Putting an unresolved address in the field reserved for
// a resolved selection is exactly the short-circuit §4.3 forbids.

import { useState } from "react";
import { copy } from "../../copy";
import { useWorkspace, workspaceStore } from "../../state/react";
import { shellStore } from "../../state/shell";
import {
  effectiveInspectorTab,
  inspectorTabsFor,
  type InspectorTab,
} from "../../state/workspace";
import { TabBar, tabControlId, useShell } from "../../system";
import { ChecksPanel } from "../inspector/ChecksPanel";
import { DfmPanel, type DescriptorIntent } from "../inspector/DfmPanel";
import { ExportPanel } from "../inspector/ExportPanel";
import { PropertiesPanel } from "../inspector/PropertiesPanel";
import { ProvenancePanel } from "../inspector/ProvenancePanel";
import { ResultsPanel } from "../inspector/ResultsPanel";
import { SourcingPanel } from "../inspector/SourcingPanel";
import { PinSplitMarker } from "../PinSplitMarker";
import { useHeldPart } from "../../state/heldPart";
import { pinSplit } from "../../state/pinSplit";
import styles from "./Inspector.module.css";

export function Inspector(): React.JSX.Element {
  const stageTab = useWorkspace((s) => s.stage_tab);
  const requested = useWorkspace((s) => s.inspector_tab);
  // The side panel's Geometry disclosure is the third place this readout can
  // appear; the drawer yields to it exactly as it yields to the stage's own
  // `results` tab (2026-09-20).
  const shell = useShell();
  const panelGeometry = shell.panelOpen.includes("results");
  const open = shell.drawerOpen;
  const tab = effectiveInspectorTab(stageTab, requested, panelGeometry);
  const tabs = inspectorTabsFor(stageTab, panelGeometry);
  const [intent, setIntent] = useState<DescriptorIntent | undefined>(undefined);
  // §4.1's held-pin marking, the selection half (J-web-viewport-9).
  const part = useWorkspace((s) => s.part);
  const pinMode = useWorkspace((s) => s.pin_mode);
  const split = pinSplit(pinMode, useHeldPart(), part);

  return (
    <section
      className={styles["drawer"]}
      aria-label={copy.inspector.tabs[tab]}
      data-drawer-open={open ? "" : undefined}
      data-inspector-collapsed={open ? undefined : ""}
    >
      {/* THE WHOLE STRIP IS THE CONTROL (2026-09-20). A chevron at one end was
          a 24px target for a fold the operator wants to hit without aiming, so
          the bar itself takes the click and the chevron is gone.

          The tabs keep their own click, because a tab is a different act: it
          chooses WHICH readout, not whether there is one. They sit inside this
          handler, so the check below is "did the click land on a control?" —
          `closest("button")` rather than `event.target === event.currentTarget`,
          since a click on a tab's icon or label targets the child, not the
          button. Only bare strip lands here.

          A `div` with an `onClick` would be an unreachable control, so the
          strip is a `button`-like region: `role="button"`, in the tab order,
          and answering Enter and Space the way a real one does. It cannot BE a
          `<button>` — it contains the tab buttons, and nesting interactive
          elements is invalid and breaks keyboard traversal. */}
      <div
        className={styles["strip"]}
        role="button"
        tabIndex={0}
        aria-expanded={open}
        aria-label={open ? copy.inspector.collapse : copy.inspector.expand}
        title={open ? copy.inspector.collapse : copy.inspector.expand}
        data-drawer-toggle=""
        onClick={(event) => {
          if ((event.target as HTMLElement).closest("button") !== null) return;
          shellStore.toggleDrawer();
        }}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget) return;
          if (event.key !== "Enter" && event.key !== " ") return;
          event.preventDefault();
          shellStore.toggleDrawer();
        }}
      >
      <TabBar
        attr="data-inspector-tab"
        panelId="inspector-panel"
        label={copy.inspector.tabsLabel}
        selected={tab}
        onSelect={(next: InspectorTab) => {
          workspaceStore.update({ inspector_tab: next });
        }}
        tabs={tabs.map((name) => ({ id: name, label: copy.inspector.tabs[name] }))}
      />
      </div>
      {/* §4.1's inherited marking, the SELECTION half (J-web-viewport-9). Two
          regions follow the pin (the stage and Export) and two follow the rail
          selection (this drawer and the Script tab); while they disagree each
          says which part it is showing, in words. */}
      {!open ? null : (
        <div data-pin-split-slot="inspector">
          <PinSplitMarker split={split} region="inspector" />
        </div>
      )}

      {!open ? null : (
      <div
        className={styles["content"]}
        role="tabpanel"
        id="inspector-panel"
        aria-labelledby={tabControlId("data-inspector-tab", tab)}
        data-inspector-panel={tab}
        data-overlay-scroll=""
      >
        {tab === "results" ? (
          <ResultsPanel />
        ) : tab === "properties" ? (
          <PropertiesPanel />
        ) : tab === "checks" ? (
          <ChecksPanel />
        ) : tab === "provenance" ? (
          <ProvenancePanel intent={intent} />
        ) : tab === "export" ? (
          <ExportPanel />
        ) : tab === "sourcing" ? (
          <SourcingPanel />
        ) : (
          <DfmPanel
            onResolveDescriptor={(next) => {
              setIntent(next);
              workspaceStore.update({ inspector_tab: "provenance" });
            }}
          />
        )}
      </div>
      )}
    </section>
  );
}
