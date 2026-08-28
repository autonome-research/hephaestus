// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `ResultsPanel` — the build result's geometry list, its per-entry visibility
// toggles, and its metrics (INTERFACE.md §6.1, §5.4).
//
// §6.1's TIGHTENING (binds G4.2) fixes the row namespace and the count:
//
//   geometry_count := len(BuildResult.geometries), served as an **explicit
//   field** by GET /parts/{part}/build.
//
//   "`ResultsPanel` renders exactly one row per `geometries` entry, each
//   carrying `data-geometry-index`."
//
// So: one row per entry, in server order, and the count beside the heading is
// the server's `geometry_count` field — never `geometries.length`, never a GLTF
// mesh count, never a `kind="solid"` row count off the selection table. The e2e
// reads `geometry_count` over HTTP and compares it to the DOM row count.
//
// §5.4 puts the visibility toggles here. What a toggle changes is a scene-graph
// property; it changes nothing about the result, and the panel says so rather
// than leaving a reader to wonder whether hiding a solid re-measured anything.
// The toggle's namespace is the geometry entry *label*, which is what the GLTF
// carries in each mesh's `extras.label` — see `state/visibility.ts` for why that
// is the only namespace available and what it costs on a multi-solid entry.

import type { BuildDocument } from "../../api/types";
import { useBuild } from "../../api/queries";
import { copy } from "../../copy";
import { Fact } from "../Fact";
import { useWorkspace } from "../../state/react";
import { visibilityKey, visibilityStore } from "../../state/visibility";
import { useSyncExternalStore } from "react";
import styles from "./panels.module.css";

/**
 * A metric's value as the server sent it, in a form `data-value` can carry.
 *
 * Serialization, never computation: a `bbox_mm` triple becomes its JSON text and
 * a number stays the number. Nothing here rounds, converts units, or combines
 * two metrics — §1's closed list names distances and volumes explicitly, and a
 * client that reformatted a measurement into a different number would be
 * computing one.
 */
function metricValue(value: unknown): string | number | boolean | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "string") {
    return value;
  }
  return JSON.stringify(value);
}

export interface ResultsViewProps {
  readonly part: string;
  readonly build: BuildDocument;
  /** Labels hidden from the viewport scene graph, from `state/visibility.ts`. */
  readonly hidden: ReadonlySet<string>;
  readonly onToggle?: ((label: string) => void) | undefined;
}

/** The panel's rendering half: a pure function of one build document. */
export function ResultsView({ part, build, hidden, onToggle }: ResultsViewProps): React.JSX.Element {
  const metrics = build.metrics ?? null;
  return (
    <section className={styles["panel"]} aria-label={copy.results.heading} data-panel="results">
      <div className={styles["headingRow"]}>
        <h3 className={styles["heading"]}>{copy.results.heading}</h3>
        {build.status === "not_built" ? null : (
          <Fact source="build.geometry_count" value={build.geometry_count} className={styles["dim"]}>
            {`${build.geometry_count} ${copy.results.count}`}
          </Fact>
        )}
      </div>

      {build.status === "not_built" ? (
        <p className={styles["absent"]}>{copy.results.notBuilt}</p>
      ) : build.status === "error" ? (
        <p className={styles["absent"]}>{copy.results.failed}</p>
      ) : (
        <>
          <ul className={styles["list"]}>
            {build.geometries.map((geometry, index) => {
              const isHidden = hidden.has(visibilityKey(part, geometry.label));
              return (
                <li
                  key={geometry.label}
                  className={styles["row"]}
                  data-geometry-row=""
                  data-geometry-index={index}
                  data-geometry-label={geometry.label}
                  data-visible={isHidden ? "false" : "true"}
                >
                  <span className={styles["rowValue"]}>
                    <Fact
                      source="build.geometries[].label"
                      value={geometry.label}
                      className={styles["mono"]}
                    />
                  </span>
                  <Fact
                    source="build.geometries[].solids"
                    value={geometry.solids}
                    className={styles["dim"]}
                  >
                    {`${geometry.solids} ${copy.results.solids}`}
                  </Fact>
                  {geometry.solids > 1 ? (
                    <span className={styles["chip"]} title={copy.results.groupNote}>
                      {copy.results.groupNote}
                    </span>
                  ) : null}
                  <button
                    type="button"
                    className={styles["toggle"]}
                    aria-pressed={isHidden}
                    data-visibility-toggle={geometry.label}
                    onClick={onToggle === undefined ? undefined : () => onToggle(geometry.label)}
                  >
                    {isHidden ? copy.results.show : copy.results.hide}
                  </button>
                </li>
              );
            })}
          </ul>
          <p className={styles["note"]}>{copy.results.hiddenNote}</p>
          {/* The viewport (§5) applies these labels to the loaded GLB's mesh
              nodes — `viewport/scene.ts::applyVisibility` reads the same store
              through `visibilityStore.hiddenLabels(part)`. The note names where
              the effect is visible, because the toggle and the picture live in
              different regions of §4.1's shell. */}
          <p className={styles["note"]}>{copy.results.appliesToViewport}</p>

          {metrics === null ? null : (
            <>
              <h3 className={styles["heading"]}>{copy.results.metricsHeading}</h3>
              <dl className={styles["pairs"]}>
                {Object.keys(metrics)
                  .sort()
                  .map((name) => (
                    <div key={name} className={styles["pairRow"]}>
                      <dt data-metric={name}>{name}</dt>
                      <dd>
                        <Fact
                          source="build.metrics[]"
                          value={metricValue(metrics[name])}
                          className={styles["mono"]}
                        />
                      </dd>
                    </div>
                  ))}
              </dl>
            </>
          )}
        </>
      )}
    </section>
  );
}

/** The container: one build read, one visibility store, no logic of its own. */
export function ResultsPanel(): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  const build = useBuild(part);
  const hidden = useSyncExternalStore(
    visibilityStore.subscribe,
    visibilityStore.getSnapshot,
    visibilityStore.getSnapshot,
  );

  if (part === null) return <p className={styles["absent"]}>{copy.inspector.selectPart}</p>;
  if (build.data === undefined) return <p className={styles["absent"]}>{copy.absent.loading}</p>;
  return (
    <ResultsView
      part={part}
      build={build.data}
      hidden={hidden}
      onToggle={(label) => {
        visibilityStore.toggle(part, label);
      }}
    />
  );
}
