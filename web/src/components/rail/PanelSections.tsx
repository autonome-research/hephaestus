// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The side panel, as four disclosures (§4.1, amended 2026-09-20).
//
// The rail used to be two kinds of thing stacked: two collapsible readouts, and
// three always-open panels that each drew their own heading. One shape means
// the operator learns the row once — every section here is a disclosure, opens
// downward in place, and several can be open at a time. An accordion would
// close the thing you were reading to show the thing you just asked for.
//
// The ORDER runs from the artifact outward: what this build MEASURES, how it
// was BUILT, what the project CONTAINS, and what git says about it.
//
// Each body is the SAME component the rest of the app renders — `ResultsPanel`,
// `Timeline`, `ProjectTree`, the git panels. A second rendering of a readout is
// a second thing to keep true, and `?tab=results` still opens the full-stage
// version, so a copy would have to agree with the original forever.

import { copy } from "../../copy";
import { shellStore, PANEL_SECTIONS, type PanelSection } from "../../state/shell";
import { Button, useShell } from "../../system";
import { ResultsPanel } from "../inspector/ResultsPanel";
import { Timeline } from "../stage/Timeline";
import { GitDirtyPanel } from "./GitDirty";
import { ProjectTree } from "./ProjectTree";
import { VersionList } from "./VersionList";
import styles from "./PanelSections.module.css";

const SECTION_TITLE: Readonly<Record<PanelSection, string>> = {
  results: copy.stage.tabs.results,
  timeline: copy.stage.tabs.timeline,
  parts: copy.rail.partsHeading,
  working_tree: copy.rail.gitHeading,
};

/** Working tree is two panels — the dirty index and the version list. */
function WorkingTree(): React.JSX.Element {
  return (
    <>
      <GitDirtyPanel />
      <VersionList />
    </>
  );
}

const SECTION_BODY: Readonly<Record<PanelSection, () => React.JSX.Element | null>> = {
  results: ResultsPanel,
  timeline: Timeline,
  parts: ProjectTree,
  working_tree: WorkingTree,
};

export function PanelSections(): React.JSX.Element {
  const open = useShell().panelOpen;

  return (
    <>
      {PANEL_SECTIONS.map((section) => {
        const expanded = open.includes(section);
        const Body = SECTION_BODY[section];
        return (
          <section key={section} className={styles["section"]} data-panel-section={section}>
            <h2 className={styles["heading"]}>
              <Button
                variant="quiet"
                icon={expanded ? "chevron-down" : "chevron-right"}
                expanded={expanded}
                className={styles["disclosure"]}
                onClick={() => {
                  shellStore.togglePanelSection(section);
                }}
                data-panel-toggle={section}
              >
                {SECTION_TITLE[section]}
              </Button>
            </h2>
            {/* Unmounted rather than hidden while collapsed: the bodies run
                their own queries, and a collapsed section that keeps polling is
                work nobody asked for. */}
            {expanded ? (
              <div className={styles["body"]} data-panel-body={section}>
                <Body />
              </div>
            ) : null}
          </section>
        );
      })}
    </>
  );
}
