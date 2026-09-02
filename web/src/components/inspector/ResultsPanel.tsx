// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `ResultsPanel` — the build result's geometry list, its per-entry visibility
// toggles, and its metrics (INTERFACE.md §6.1, §5.4, §4.7).
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
// mesh count, never a `kind="solid"` row count off the selection table.
//
// §5.4 puts the visibility toggles here. What a toggle changes is a scene-graph
// property; it changes nothing about the result, and the panel says so rather
// than leaving a reader to wonder whether hiding a solid re-measured anything.
//
// §4.7's METRICS TABLE IS THE FOUR-DEFECT FIX. The metrics were a `<dl>` of raw
// SCREAMING_SNAKE keys with left-aligned values and no tabular figures, and one
// of those values was `74289.99999999999` shipped to an engineer as a
// measurement. They are now a `DataTable`: the key becomes a label and a unit in
// their own columns (`format.ts`, and a key with no declared suffix gets NO
// unit rather than a guessed one), the value is right-aligned and tabular, and
// `<Fact>`'s `data-value` still carries the server's number to fourteen digits
// so the e2e's DOM-vs-JSON comparison reads exactly what it read before.

import type { BuildDocument } from "../../api/types";
import { useBuild } from "../../api/queries";
import { copy } from "../../copy";
import {
  Button,
  Chip,
  DataTable,
  EmptyState,
  Panel,
  PanelBody,
  PanelHeader,
  PanelNote,
  PanelSection,
  formatValue,
  metricLabel,
  metricUnit,
} from "../../system";
import { formatSolids } from "../../system/format";
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
 * computing one. `formatValue` decides only what a human SEES; `data-value`
 * keeps the server's own bytes.
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
  /**
   * How many of THIS part's entries are hidden.
   *
   * Client state, not a server count — §1 exempts it by name where the grid
   * readout used to carry it ("How many solids the viewer has hidden — client
   * state, not a server count"), and it is deliberately not a `<Fact>`.
   *
   * It reads here rather than in the viewport overlay for two reasons: §5.5
   * defines that overlay as "camera state and scale", which this is not; and an
   * overlay that grows a row when a solid is hidden puts chrome pixels into
   * G4.5's control region, measured at 1.10% against a ≤1% ceiling. See
   * `GridReadout.tsx`'s header for the measurement.
   */
  const hiddenCount = build.geometries.filter((geometry) =>
    hidden.has(visibilityKey(part, geometry.label)),
  ).length;
  return (
    <Panel label={copy.results.heading} data-panel="results">
      <PanelHeader
        title={copy.results.heading}
        level={3}
        actions={
          build.status === "not_built" ? undefined : (
            <>
              <Chip data-results-count="">
                <Fact source="build.geometry_count" value={build.geometry_count}>
                  {`${String(build.geometry_count)} ${copy.results.count}`}
                </Fact>
              </Chip>
              {hiddenCount === 0 ? null : (
                <Chip data-results-hidden={hiddenCount}>
                  {copy.results.hiddenCount(hiddenCount)}
                </Chip>
              )}
            </>
          )
        }
      />
      <PanelBody>
        {build.status === "not_built" ? (
          <EmptyState icon="cube" title={copy.results.notBuiltTitle} body={copy.results.notBuilt} />
        ) : build.status === "error" ? (
          <EmptyState icon="alert" title={copy.results.failedTitle} body={copy.results.failed} />
        ) : (
          <>
            {/* §6.1 (C16): the visibility toggles form a COLUMN. The verb is
                printed exactly once, here in the column header, and never in a
                row — each row's compact toggle carries the complete accessible
                name (`Hide <label>` / `Show <label>`) instead. The header word
                is presentation for sighted scanning; it is aria-hidden so a
                screen reader hears each toggle's own full name, once. */}
            <div className={styles["listHeader"]} aria-hidden="true" data-visibility-header="">
              <span className={styles["toggleHeader"]}>{copy.results.hideHeader}</span>
            </div>
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
                      className={styles["muted"]}
                    >
                      {/* §6.1 (C17): `1 solid`, `N solids` — the unit word
                          inflects in `format.ts`, the served count does not. */}
                      {formatSolids(geometry.solids)}
                    </Fact>
                    {geometry.solids > 1 ? (
                      <Chip title={copy.results.groupNote} data-geometry-group="">
                        {copy.results.group}
                      </Chip>
                    ) : null}
                    <Button
                      variant="toggle"
                      pressed={isHidden}
                      icon={isHidden ? "dash" : "dot"}
                      iconLabel={
                        isHidden
                          ? copy.results.showSolid(geometry.label)
                          : copy.results.hideSolid(geometry.label)
                      }
                      title={isHidden ? copy.results.show : copy.results.hide}
                      className={styles["visibilityToggle"]}
                      onClick={onToggle === undefined ? undefined : () => onToggle(geometry.label)}
                      data-visibility-toggle={geometry.label}
                    />
                  </li>
                );
              })}
            </ul>
            {/* ONE note, and only once hiding is in play.
                The panel shipped two permanent paragraphs about the toggles —
                that hiding is a scene-graph property, and that the effect is
                visible on the Viewport tab — under every built part's geometry
                list, whether or not anything was hidden. The fact answers a
                question ("did hiding re-measure anything?") that a reader can
                only have after they have hidden something, so it is printed
                then. `viewport/scene.ts::applyVisibility` reads the same store
                through `visibilityStore.hiddenLabels(part)`. */}
            {hiddenCount === 0 ? null : (
              <PanelNote data-results-hidden-note="">{copy.results.hiddenNote}</PanelNote>
            )}

            {metrics === null ? null : (
              <PanelSection eyebrow={copy.results.metricsHeading}>
                {/* §4.7 (C27): the METRICS table renders two label/value/unit
                    column groups when the inspector drawer's CONTENT width is
                    ≥640px, single column below. The switch is a container
                    query on this wrapper — the drawer's own measured width, a
                    container fact, never a new viewport-breakpoint authority.
                    Layout only: rows, `<Fact>` sources, and `format.ts`
                    boundaries are byte-identical in both forms. */}
                <div className={styles["metricsHost"]} data-metrics-split="">
                  <DataTable
                    split
                    rows={Object.keys(metrics)
                    .sort()
                    .map((name) => ({
                      key: name,
                      label: metricLabel(name),
                      value: (
                        <Fact source="build.metrics[]" value={metricValue(metrics[name])}>
                          {formatValue(metrics[name])}
                        </Fact>
                      ),
                      unit: metricUnit(name) ?? "",
                      attrs: { "data-metric": name },
                    }))}
                  />
                </div>
              </PanelSection>
            )}
          </>
        )}
      </PanelBody>
    </Panel>
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

  if (part === null) {
    return <EmptyState icon="cube" title={copy.inspector.noPartTitle} body={copy.inspector.selectPart} />;
  }
  if (build.data === undefined) return <PanelNote>{copy.absent.loading}</PanelNote>;
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
