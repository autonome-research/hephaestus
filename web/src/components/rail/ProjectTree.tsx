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

import { useBuild, useParts } from "../../api/queries";
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
import { DirtyMarker, useDirtyIndex, type DirtyIndex } from "./GitDirty";
import styles from "./ProjectTree.module.css";

export function ProjectTree(): React.JSX.Element {
  const parts = useParts();
  const dirty = useDirtyIndex();
  const selected = useWorkspace((s) => s.part);

  return (
    <Panel className={styles["panel"]} label={copy.rail.partsHeading}>
      <PanelHeader title={copy.rail.partsHeading} level={2} />
      <PanelBody className={styles["body"]}>
        {parts.data === undefined ? (
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
        ) : (
          <Tree label={copy.rail.partsHeading}>
            {parts.data.parts.map((part) => (
              <PartNode
                key={part.name}
                part={part}
                dirty={dirty}
                selected={selected === part.name}
              />
            ))}
          </Tree>
        )}
      </PanelBody>
    </Panel>
  );
}

interface PartNodeProps {
  readonly part: PartSummary;
  readonly dirty: DirtyIndex;
  readonly selected: boolean;
}

function PartNode({ part, dirty, selected }: PartNodeProps): React.JSX.Element {
  // The build is fetched for the selected part only. A rail that fetched every
  // part's build on mount would turn opening a project into N builds' worth of
  // reads for rows nobody has looked at yet.
  const build = useBuild(part.name, selected);
  const entry = dirty.byPart.get(part.name);
  const built = build.data;

  const open = (): void => {
    workspaceStore.update({ part: part.name, selection: null, measure: null });
  };

  return (
    <TreeRow
      depth={0}
      selected={selected}
      expanded={selected}
      onSelect={open}
      onToggle={open}
      data-part={part.name}
      data-tree-row="part"
      label={<Fact source="parts[].name" value={part.name} className={styles["partName"]} />}
      trailing={
        <>
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
      {selected && built !== undefined && built.geometries.length > 0 ? (
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
