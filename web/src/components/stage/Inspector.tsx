// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The INSPECTOR drawer (INTERFACE.md §4.1) — the five tabs of §4.2's panel
// inventory, as a bottom drawer of the Stage rather than a third column.
//
// §4.1: "INSPECTOR is a bottom drawer of the Stage rather than a third column:
// its content is *about the thing in the Stage*, and losing that spatial
// relation costs more than the vertical pixels."
//
// The tab is workspace state (`inspector_tab`, §4.5), so the drawer's selection
// is in the URL and survives a reload like everything else. All five panels of
// the closed inventory are mounted; each is a projection of one read route and
// owns its own named absences (§6.1–§6.4, §4.4).
//
// ONE PIECE OF STATE LIVES HERE AND NOWHERE ELSE: the descriptor a reader
// clicked in the DFM panel. §6.4 makes a finding's topology descriptor clickable
// and says it "drives the same server resolve path as a raycast (§12.3) against
// the finding's `source_artifact_ref`" — so the click is a *navigation along
// §4.3's spine*, from a finding to the provenance station. It is deliberately
// not workspace state: §4.5's record is closed, its `selection` field is a
// resolved server selection, and a clicked descriptor is not one (see
// `DfmPanel`'s `DescriptorIntent` for why the resolve route cannot accept a
// descriptor yet). Putting an unresolved address in the field reserved for a
// resolved selection is exactly the short-circuit §4.3 forbids.

import { useState } from "react";
import { copy } from "../../copy";
import { useWorkspace, workspaceStore } from "../../state/react";
import { INSPECTOR_TABS, type InspectorTab } from "../../state/workspace";
import { ChecksPanel } from "../inspector/ChecksPanel";
import { DfmPanel, type DescriptorIntent } from "../inspector/DfmPanel";
import { PropertiesPanel } from "../inspector/PropertiesPanel";
import { ProvenancePanel } from "../inspector/ProvenancePanel";
import { ResultsPanel } from "../inspector/ResultsPanel";
import styles from "./Inspector.module.css";

export function Inspector(): React.JSX.Element {
  const tab = useWorkspace((s) => s.inspector_tab);
  const [intent, setIntent] = useState<DescriptorIntent | undefined>(undefined);

  return (
    <section className={styles["drawer"]} aria-label={copy.inspector.tabs[tab]}>
      <div className={styles["tabs"]} role="tablist">
        {INSPECTOR_TABS.map((name: InspectorTab) => (
          <button
            key={name}
            type="button"
            role="tab"
            aria-selected={tab === name}
            className={styles["tab"]}
            data-inspector-tab={name}
            onClick={() => {
              workspaceStore.update({ inspector_tab: name });
            }}
          >
            {copy.inspector.tabs[name]}
          </button>
        ))}
      </div>
      <div className={styles["content"]} role="tabpanel" data-inspector-panel={tab}>
        {tab === "results" ? (
          <ResultsPanel />
        ) : tab === "properties" ? (
          <PropertiesPanel />
        ) : tab === "checks" ? (
          <ChecksPanel />
        ) : tab === "provenance" ? (
          <ProvenancePanel intent={intent} />
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
