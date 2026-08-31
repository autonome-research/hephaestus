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
// the declared manufacturing-identity fields.
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
import { INSPECTOR_TABS, type InspectorTab } from "../../state/workspace";
import { TabBar } from "../../system";
import { ChecksPanel } from "../inspector/ChecksPanel";
import { DfmPanel, type DescriptorIntent } from "../inspector/DfmPanel";
import { ExportPanel } from "../inspector/ExportPanel";
import { PropertiesPanel } from "../inspector/PropertiesPanel";
import { ProvenancePanel } from "../inspector/ProvenancePanel";
import { ResultsPanel } from "../inspector/ResultsPanel";
import { SourcingPanel } from "../inspector/SourcingPanel";
import styles from "./Inspector.module.css";

export function Inspector(): React.JSX.Element {
  const tab = useWorkspace((s) => s.inspector_tab);
  const [intent, setIntent] = useState<DescriptorIntent | undefined>(undefined);

  return (
    <section className={styles["drawer"]} aria-label={copy.inspector.tabs[tab]}>
      <TabBar
        attr="data-inspector-tab"
        label={copy.inspector.tabsLabel}
        selected={tab}
        onSelect={(next: InspectorTab) => {
          workspaceStore.update({ inspector_tab: next });
        }}
        tabs={INSPECTOR_TABS.map((name) => ({ id: name, label: copy.inspector.tabs[name] }))}
      />
      <div className={styles["content"]} role="tabpanel" data-inspector-panel={tab}>
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
    </section>
  );
}
