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
// consult the GLTF.
//
// The inline dirty marker comes from §13.1's git projection and from nothing
// else — a part can be clean and unbuilt, or dirty and current, and this tree
// shows the two axes side by side without joining them.

import { useBuild, useParts } from "../../api/queries";
import { copy } from "../../copy";
import type { PartSummary } from "../../api/types";
import { useWorkspace, workspaceStore } from "../../state/react";
import { Fact } from "../Fact";
import { DirtyMarker, useDirtyIndex, type DirtyIndex } from "./GitDirty";
import styles from "./ProjectTree.module.css";

export function ProjectTree(): React.JSX.Element {
  const parts = useParts();
  const dirty = useDirtyIndex();
  const selected = useWorkspace((s) => s.part);

  return (
    <section className={styles["panel"]} aria-label={copy.rail.partsHeading}>
      <h2 className={styles["heading"]}>{copy.rail.partsHeading}</h2>
      {parts.data === undefined ? (
        <p className={styles["absent"]}>{copy.absent.loading}</p>
      ) : parts.data.parts.length === 0 ? (
        <p className={styles["absent"]}>{copy.rail.partsEmpty}</p>
      ) : (
        <ul className={styles["tree"]} role="tree" aria-label={copy.rail.partsHeading}>
          {parts.data.parts.map((part) => (
            <PartNode
              key={part.name}
              part={part}
              dirty={dirty}
              selected={selected === part.name}
            />
          ))}
        </ul>
      )}
    </section>
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

  return (
    <li
      className={styles["node"]}
      role="treeitem"
      aria-selected={selected}
      aria-expanded={selected}
      data-part={part.name}
    >
      <div className={styles["partRow"]} data-tree-row="part" data-part={part.name}>
        <button
          type="button"
          className={styles["partButton"]}
          onClick={() => {
            workspaceStore.update({ part: part.name, selection: null, measure: null });
          }}
        >
          <span className={styles["twisty"]} aria-hidden="true">
            {selected ? "▾" : "▸"}
          </span>
          <Fact source="parts[].name" value={part.name} className={styles["partName"]} />
        </button>
        {entry === undefined ? null : <DirtyMarker entry={entry} />}
        {selected && built !== undefined ? (
          <span className={styles["counts"]}>
            {built.status === "not_built" ? (
              <span className={styles["absentInline"]}>{copy.rail.notBuilt}</span>
            ) : built.status === "error" ? (
              <span className={styles["failed"]}>{copy.rail.buildFailed}</span>
            ) : (
              <Fact
                source="build.geometry_count"
                value={built.geometry_count}
                className={styles["count"]}
              >
                {`${built.geometry_count} ${copy.rail.geometryCount}`}
              </Fact>
            )}
          </span>
        ) : null}
      </div>

      {selected && built !== undefined && built.geometries.length > 0 ? (
        <ul className={styles["geometries"]} role="group">
          {built.geometries.map((geometry, index) => (
            <li
              key={geometry.label}
              role="treeitem"
              aria-selected={false}
              className={styles["geometryRow"]}
              data-tree-row="geometry"
              data-part={part.name}
              data-geometry-index={index}
              data-geometry-label={geometry.label}
            >
              <Fact
                source="build.geometries[].label"
                value={geometry.label}
                className={styles["geometryLabel"]}
              />
              <Fact
                source="build.geometries[].solids"
                value={geometry.solids}
                className={styles["solids"]}
              />
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}
