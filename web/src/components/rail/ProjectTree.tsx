// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `ProjectTree` — the rail's part tree, and the surface G4.2 counts.
//
// G4.2 (mission_plan.md): "tree row count equals build-result geometry count".
// §6.1's TIGHTENING names which of the three plausible numbers that is:
//
//   geometry_count := len(BuildResult.geometries), served as an **explicit
//   field** by `GET /parts/{part}/build`.
//
// So a part's children in this tree are **exactly its `geometries` entries, one
// row each**, and the count beside the part is the server's `geometry_count`
// field — never `geometries.length` computed here, never a GLTF mesh count,
// never a `kind="solid"` row count off the selection table. The eslint rule
// would reject the `.length` spelling and it is right to: §1's closed list ends
// with "any re-count of anything a build result already counts".
//
// The e2e reads `geometry_count` over HTTP and compares it to the DOM row count
// (`[data-tree-row="geometry"]`); it does not recount client-side and does not
// consult the GLTF. **Both of the selectors it uses are preserved verbatim** by
// the `TreeRow` primitive that now owns the rows (§3.14's migration criterion).
//
// §4.7's TreeRow retires two shipped defects here: a tree that claimed
// `role="tree"` and handled no key at all, and a colour-only dirty marker. The
// marker is now a `Badge` carrying a word and an icon, from §13.1's git
// projection and from nothing else — a part can be clean and unbuilt, or dirty
// and current, and this tree shows the two axes side by side without joining
// them.
//
// Parts and the five closed sections (Analyses / Docs / Globals / Imports /
// Materials) are one `role="tree"` (#65). Collapsed is a tree-item state, not
// a second widget. Sections stay listed even when empty; an expanded section
// is an empty-honest absence. Git dirty stays in `GitDirty` (§13.1); this
// tree does not hide `.heph/` rows.

import { useState, useSyncExternalStore } from "react";
import { useBuild, useParts } from "../../api/queries";
import { turnChangedStore } from "../../api/refresh";
import { copy } from "../../copy";
import type { PartSummary } from "../../api/types";
import { useWorkspace, workspaceStore } from "../../state/react";
import {
  Chip,
  EmptyState,
  Panel,
  PanelBody,
  PanelHeader,
  Tree,
  TreeGroup,
  TreeRow,
} from "../../system";
import { Fact } from "../Fact";
import { RefusalBanner } from "../RefusalBanner";
import { DirtyMarker, useDirtyIndex, type DirtyIndex } from "./GitDirty";
import styles from "./ProjectTree.module.css";

/**
 * Closed project-tree sections. Always listed, even when empty: the engine
 * has no HTTP projection for analyses / docs / globals / imports / materials
 * today, so an expanded section is an empty-honest absence — not a catalog
 * invented from a registry or a walk of the project root.
 */
export const PROJECT_TREE_SECTIONS = [
  "analyses",
  "docs",
  "globals",
  "imports",
  "materials",
] as const;
export type ProjectTreeSection = (typeof PROJECT_TREE_SECTIONS)[number];

export function ProjectTree(): React.JSX.Element {
  const parts = useParts();
  const dirty = useDirtyIndex();
  const selected = useWorkspace((s) => s.part);
  // §7A.11 (C7): the rows the last agent turn touched. The store is written by
  // `refreshAfterTurn`'s two-projection diff and by nothing else, so history
  // load, resync, and pin movement cannot mint a mark here.
  const turnChanged = useSyncExternalStore(
    turnChangedStore.subscribe,
    turnChangedStore.getSnapshot,
    turnChangedStore.getSnapshot,
  );
  const [open, setOpen] = useState<ReadonlySet<ProjectTreeSection>>(() => new Set());

  const toggle = (id: ProjectTreeSection): void => {
    setOpen((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <Panel className={styles["panel"]} label={copy.rail.partsHeading}>
      <PanelHeader title={copy.rail.partsHeading} level={2} />
      <PanelBody className={styles["body"]}>
        {parts.error !== null ? (
          <RefusalBanner
            error={parts.error}
            onRetry={() => {
              void parts.refetch();
            }}
          />
        ) : parts.data === undefined ? (
          <p className={styles["absent"]}>{copy.absent.loading}</p>
        ) : parts.data.parts.length === 0 ? (
          // §7A.2's "where a part comes from, said out loud". After the
          // composer lands, the only way to bring a part into existence from
          // the browser is to type English at an orchestrator agent, which
          // calls `create_part` — there is no part-creation route, no button,
          // and none is added (§15.9 forbids the workspace inventing model
          // tools, and a part is authored source, not a form). So what this
          // state owes the operator is not a button but an ENTRY POINT: it
          // names the mechanism and points at the column that has it.
          //
          // **A blank canvas the operator has to guess is filled by talking is
          // the same defect as a composer that is not there.**
          //
          // Project creation is further out of reach and is refused by name
          // (§15.30): `heph serve` opens an EXISTING project root.
          <EmptyState
            icon="cube"
            density="inline"
            title={copy.rail.partsEmptyTitle}
            body={
              <>
                <p>{copy.rail.partsEmpty}</p>
                <p data-parts-empty-entry="">{copy.composer.blankCanvas}</p>
                <p>{copy.composer.noProject}</p>
              </>
            }
          />
        ) : null}
        <Tree label={copy.rail.title}>
          {parts.data?.parts.map((part) => (
            <PartNode
              key={part.name}
              part={part}
              dirty={dirty}
              selected={selected === part.name}
              changed={turnChanged.has(part.name)}
            />
          ))}
          <ProjectSectionList open={open} onToggle={toggle} />
        </Tree>
      </PanelBody>
    </Panel>
  );
}

/**
 * The five closed sections, as tree items. Split out so a test can assert the
 * inventory and the empty-honest expanded body without standing up `GET /parts`.
 * The caller wraps them in the same `Tree` as the parts (#65).
 */
export function ProjectSectionList({
  open,
  onToggle,
}: {
  readonly open: ReadonlySet<ProjectTreeSection>;
  readonly onToggle: (id: ProjectTreeSection) => void;
}): React.JSX.Element {
  return (
    <>
      {PROJECT_TREE_SECTIONS.map((id) => {
        const expanded = open.has(id);
        return (
          <TreeRow
            key={id}
            depth={0}
            selected={false}
            expanded={expanded}
            onSelect={() => {
              onToggle(id);
            }}
            onToggle={() => {
              onToggle(id);
            }}
            data-tree-row="section"
            data-tree-section={id}
            label={copy.rail.sections[id]}
          >
            {expanded ? (
              <TreeGroup>
                <li role="none">
                  <EmptyState
                    icon="file"
                    density="inline"
                    title={copy.rail.sectionEmptyTitle}
                    body={copy.rail.sectionEmpty}
                    data-tree-section-empty={id}
                  />
                </li>
              </TreeGroup>
            ) : null}
          </TreeRow>
        );
      })}
    </>
  );
}

interface PartNodeProps {
  readonly part: PartSummary;
  readonly dirty: DirtyIndex;
  readonly selected: boolean;
  /** §7A.11 (C7): this row's build ref changed across the last agent turn. */
  readonly changed: boolean;
}

function PartNode({ part, dirty, selected, changed }: PartNodeProps): React.JSX.Element {
  // The build is fetched for the selected part only. A rail that fetched every
  // part's build on mount would turn opening a project into N builds' worth of
  // reads for rows nobody has looked at yet.
  const build = useBuild(part.name, selected);
  const entry = dirty.byPart.get(part.name);
  const built = build.data;
  const [expanded, setExpanded] = useState(selected);
  const [selectedWhenSet, setSelectedWhenSet] = useState(selected);
  if (selected !== selectedWhenSet) {
    setSelectedWhenSet(selected);
    if (selected) setExpanded(true);
  }
  const canExpand = selected && built !== undefined && built.geometries.length > 0;

  const open = (): void => {
    setExpanded(true);
    // C7: clicking the row is one of the marker's two exits (the other is the
    // next turn's settle). Nothing else clears it — not re-renders, not
    // selection arriving from elsewhere.
    turnChangedStore.clear(part.name);
    workspaceStore.update({ part: part.name, selection: null, measure: null });
  };

  return (
    <TreeRow
      depth={0}
      selected={selected}
      {...(canExpand
        ? {
            expanded,
            onToggle: () => {
              setExpanded((current) => !current);
            },
          }
        : {})}
      onSelect={open}
      data-part={part.name}
      data-tree-row="part"
      {...(changed ? { "data-turn-changed": "" } : {})}
      label={<Fact source="parts[].name" value={part.name} className={styles["partName"]} />}
      trailing={
        <>
          {/* C7: the quiet marker. A word, not a bare dot (§4.7's trailing
              rule), and it renders no value — it says *this changed*; the
              value is behind the click, on the server projection. */}
          {changed ? (
            <Chip
              className={styles["turnChanged"]}
              title={copy.rail.turnChangedTitle}
              data-turn-marker=""
            >
              {copy.rail.turnChanged}
            </Chip>
          ) : null}
          {entry === undefined ? null : <DirtyMarker entry={entry} />}
          {selected && built !== undefined ? (
            built.status === "not_built" ? (
              <Chip data-part-state="not_built">{copy.rail.notBuilt}</Chip>
            ) : built.status === "error" ? (
              <Chip data-part-state="failed">{copy.rail.buildFailed}</Chip>
            ) : (
              <Chip data-part-state="built">
                <Fact source="build.geometry_count" value={built.geometry_count}>
                  {`${String(built.geometry_count)} ${copy.rail.geometryCount}`}
                </Fact>
              </Chip>
            )
          ) : null}
        </>
      }
    >
      {canExpand && expanded && built !== undefined ? (
        <TreeGroup>
          {built.geometries.map((geometry, index) => (
            <TreeRow
              key={geometry.label}
              depth={1}
              selected={false}
              data-tree-row="geometry"
              data-part={part.name}
              data-geometry-index={index}
              data-geometry-label={geometry.label}
              label={
                <Fact
                  source="build.geometries[].label"
                  value={geometry.label}
                  className={styles["geometryLabel"]}
                />
              }
              trailing={
                <Fact
                  source="build.geometries[].solids"
                  value={geometry.solids}
                  className={styles["solids"]}
                />
              }
            />
          ))}
        </TreeGroup>
      ) : null}
    </TreeRow>
  );
}
