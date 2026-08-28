// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `DfmPanel` — the manufacturability findings (INTERFACE.md §6.4).
//
// §6.4 is the orphaned G6 clause given a home. What it asks this panel to render
// is enumerated, and every item of the list is here:
//
//   "`severity_counts` header, findings list, `errored_rules`, a `truncated`
//   marker, `process`, pack `{name, version, registry, registry_digest}`,
//   `material`, and `resolved_from ∈ {current, artifact_ref, project_snapshot}`
//   as a visible chip."
//
//   "Each finding renders `rule_id`, `severity`, `title`, `message`, `measured`,
//   `suggested_bound` + `bound_unit`, `tags`, and **artifact-bound topology
//   descriptors** `{kind, solid_id, topology_index, tag}`. G6 pins that findings
//   report descriptors 'rather than bare mask IDs', so the panel renders the
//   descriptor and never the raw integer alone."
//
// THE TWO CONTROLS ARE NOT COLLAPSED, AND NEITHER IS BUILT HERE. §6.4 splits the
// "DFM toggle" into (a) a **Run DFM** action (`POST /parts/{part}/dfm`) and (b) a
// project-settings write (`POST /project/config/dfm`), because `[dfm] auto_run`
// is a project setting and not a per-message flag. This panel is the read half:
// it shows `auto_run` as a fact and offers neither control. Both are keyed
// mutations and belong with the rest of the mutation surface.
//
// `data-dfm-source` — §6.4 requires a finding on a transient preview and a
// finding on the current artifact to be *distinguishable in the panel*. The
// engine's `resolved_from` has three values and §6.4's attribute has two, so both
// are emitted: `data-dfm-resolved-from` carries the engine's word unrewritten,
// and `data-dfm-source` carries §6.4's `current` / `preview` distinction over it.
// Collapsing three into two without keeping the three would lose the difference
// between a transient preview and a project snapshot.

import type { DfmDocument, DfmFinding, DfmRun, TopologyDescriptor } from "../../api/types";
import { useDfm, useProject } from "../../api/queries";
import { copy } from "../../copy";
import { Fact } from "../Fact";
import { useWorkspace } from "../../state/react";
import styles from "./panels.module.css";

/**
 * The intent a clicked descriptor expresses (§6.4, §12.3).
 *
 * §6.4: "A descriptor is **clickable** and drives the same server resolve path
 * as a raycast (§12.3) against the finding's `source_artifact_ref`."
 *
 * DEVIATION, recorded rather than papered over: **that path does not exist
 * yet, and its request shapes do not accept a descriptor.** §12.3's route takes
 * a GLTF pick `{build_artifact_ref, gltf_artifact_ref, mesh_index,
 * primitive_index?}` or a mask submission `{build_artifact_ref,
 * selection_artifact_ref, selection_id}`; a `TopologyDescriptor` is neither, and
 * turning `(kind, solid_id, topology_index)` into a `selection_id` is a lookup in
 * the selection table — a server operation nothing exposes (§19 item 8). So the
 * click emits this intent and the workspace routes it to the Provenance panel,
 * which renders the artifact-bound address the finding carries and names the
 * station of §4.3's spine that is missing. It never fabricates a resolution, and
 * the day the route lands the handler is the only thing that changes.
 */
export interface DescriptorIntent {
  readonly part: string;
  readonly source_artifact_ref: string;
  readonly rule_id: string;
  readonly descriptor: TopologyDescriptor;
}

/** §6.4's two-value attribute over the engine's three-value `resolved_from`. */
export function dfmSource(run: DfmRun): "current" | "preview" {
  return run.resolved_from === "current" ? "current" : "preview";
}

/** A finding's `measured` map as the rule reported it. Serialized, not computed. */
function measuredText(measured: unknown): string {
  return measured === undefined || measured === null ? "" : JSON.stringify(measured);
}

/** One descriptor, as a control. Never the bare integer (§6.4). */
function Descriptor({
  descriptor,
  index,
  onResolve,
}: {
  readonly descriptor: TopologyDescriptor;
  readonly index: number;
  readonly onResolve?: (() => void) | undefined;
}): React.JSX.Element {
  return (
    <button
      type="button"
      className={styles["descriptor"]}
      title={copy.dfm.descriptorTitle}
      data-dfm-descriptor={index}
      data-descriptor-kind={descriptor.kind}
      data-descriptor-solid={descriptor.solid_id}
      data-descriptor-index={descriptor.topology_index}
      data-descriptor-tag={descriptor.tag ?? ""}
      onClick={onResolve}
    >
      <Fact source="dfm.last.findings[].topology[].kind" value={descriptor.kind} />
      <Fact source="dfm.last.findings[].topology[].solid_id" value={descriptor.solid_id} />
      <Fact
        source="dfm.last.findings[].topology[].topology_index"
        value={descriptor.topology_index}
      />
      {descriptor.tag === null ? null : (
        <Fact source="dfm.last.findings[].topology[].tag" value={descriptor.tag} />
      )}
    </button>
  );
}

function Finding({
  finding,
  index,
  source,
  onResolve,
}: {
  readonly finding: DfmFinding;
  readonly index: number;
  readonly source: "current" | "preview";
  readonly onResolve?: ((intent: TopologyDescriptor) => void) | undefined;
}): React.JSX.Element {
  return (
    <li
      className={styles["finding"]}
      data-dfm-finding={index}
      data-dfm-rule={finding.rule_id}
      data-dfm-severity={finding.severity}
      data-dfm-source={source}
    >
      <div className={styles["findingHead"]}>
        <span className={styles["badge"]} data-severity={finding.severity}>
          <Fact source="dfm.last.findings[].severity" value={finding.severity} />
        </span>
        <Fact
          source="dfm.last.findings[].title"
          value={finding.title}
          className={styles["findingTitle"]}
        />
        <Fact
          source="dfm.last.findings[].rule_id"
          value={finding.rule_id}
          className={styles["findingRule"]}
        />
      </div>

      <Fact source="dfm.last.findings[].message" value={finding.message} />

      <div className={styles["chips"]}>
        <span className={styles["chip"]}>
          {copy.dfm.measured}:{" "}
          <Fact
            source="dfm.last.findings[].measured"
            value={measuredText(finding.measured)}
            className={styles["mono"]}
          />
        </span>
        {finding.suggested_bound === null ? null : (
          <span className={styles["chip"]}>
            {copy.dfm.suggested}:{" "}
            <Fact
              source="dfm.last.findings[].suggested_bound"
              value={finding.suggested_bound}
              className={styles["mono"]}
            />{" "}
            <Fact source="dfm.last.findings[].bound_unit" value={finding.bound_unit} />
          </span>
        )}
        {finding.tags.map((tag) => (
          <span key={tag} className={styles["chip"]} data-dfm-tag={tag}>
            <Fact source="dfm.last.findings[].tags[]" value={tag} className={styles["mono"]} />
          </span>
        ))}
      </div>

      <div className={styles["chips"]}>
        <span className={styles["rowName"]}>{copy.dfm.topology}</span>
        {finding.topology.map((descriptor, descriptorIndex) => (
          <Descriptor
            key={`${descriptor.kind}-${descriptor.solid_id}-${descriptor.topology_index}`}
            descriptor={descriptor}
            index={descriptorIndex}
            onResolve={onResolve === undefined ? undefined : () => onResolve(descriptor)}
          />
        ))}
      </div>
    </li>
  );
}

export interface DfmViewProps {
  readonly dfm: DfmDocument;
  /**
   * `capabilities.secure_executor` from `GET /project`.
   *
   * §6.4: "`capability_not_available` (no sandbox) renders as an explicit
   * explanatory refusal card, never an empty list. Silence never reads as a
   * pass." The recorded-run route answers `last: null` for both "never run" and
   * "refused", so the panel reads the project's own capability to tell a machine
   * that *cannot* evaluate from one that has not yet been asked to.
   */
  readonly secureExecutor?: boolean | undefined;
  readonly onResolveDescriptor?: ((intent: DescriptorIntent) => void) | undefined;
}

export function DfmView({
  dfm,
  secureExecutor,
  onResolveDescriptor,
}: DfmViewProps): React.JSX.Element {
  const run = dfm.last;
  const source = run === null ? null : dfmSource(run);
  const severities = run === null ? [] : Object.keys(run.severity_counts).sort();

  return (
    <section
      className={styles["panel"]}
      aria-label={copy.dfm.heading}
      data-panel="dfm"
      data-dfm-source={source ?? ""}
      data-dfm-resolved-from={dfm.resolved_from ?? ""}
    >
      <div className={styles["headingRow"]}>
        <h3 className={styles["heading"]}>{copy.dfm.heading}</h3>
        <span className={styles["chip"]} data-dfm-auto-run={String(dfm.auto_run)}>
          {copy.dfm.autoRun}:{" "}
          <Fact source="dfm.auto_run" value={dfm.auto_run}>
            {dfm.auto_run ? copy.dfm.autoRunOn : copy.dfm.autoRunOff}
          </Fact>
        </span>
      </div>
      <p className={styles["note"]}>{copy.dfm.autoRunNote}</p>

      {run === null ? (
        <p className={styles["absent"]} data-dfm-absence={secureExecutor === false ? "capability" : "no_run"}>
          {secureExecutor === false ? copy.dfm.capabilityRefused : copy.dfm.absent}
        </p>
      ) : (
        <>
          <dl className={styles["pairs"]}>
            <div className={styles["pairRow"]}>
              <dt>{copy.dfm.resolvedFrom}</dt>
              <dd>
                <span className={styles["state"]} data-dfm-resolved-from={run.resolved_from}>
                  <Fact source="dfm.last.resolved_from" value={run.resolved_from}>
                    {copy.dfm.resolved[run.resolved_from]}
                  </Fact>
                </span>{" "}
                <Fact
                  source="dfm.last.source_artifact_ref"
                  value={run.source_artifact_ref}
                  className={styles["mono"]}
                  mono
                />
              </dd>
            </div>
            <div className={styles["pairRow"]}>
              <dt>{copy.dfm.process}</dt>
              <dd>
                <Fact source="dfm.last.process" value={run.process} />
              </dd>
            </div>
            <div className={styles["pairRow"]}>
              <dt>{copy.dfm.pack}</dt>
              <dd>
                <Fact source="dfm.last.pack.name" value={run.pack.name} />{" "}
                <Fact source="dfm.last.pack.version" value={run.pack.version} />
              </dd>
            </div>
            <div className={styles["pairRow"]}>
              <dt>{copy.dfm.registry}</dt>
              <dd>
                <Fact source="dfm.last.pack.registry" value={run.pack.registry} />{" "}
                <Fact
                  source="dfm.last.pack.registry_digest"
                  value={run.pack.registry_digest}
                  className={styles["mono"]}
                  mono
                />
              </dd>
            </div>
            <div className={styles["pairRow"]}>
              <dt>{copy.dfm.material}</dt>
              <dd>
                {run.material === null ? (
                  <span className={styles["dim"]}>{copy.absent.unavailable}</span>
                ) : (
                  <Fact
                    source="dfm.last.material.name"
                    value={String(run.material["name"] ?? "")}
                  />
                )}
              </dd>
            </div>
          </dl>

          <div className={styles["chips"]}>
            <span className={styles["rowName"]}>{copy.dfm.severity}</span>
            {severities.length === 0 ? (
              <span className={styles["chip"]}>{copy.dfm.clean}</span>
            ) : (
              severities.map((severity) => (
                <span key={severity} className={styles["badge"]} data-severity={severity}>
                  {severity}:{" "}
                  <Fact
                    source="dfm.last.severity_counts[]"
                    value={run.severity_counts[severity] ?? null}
                  />
                </span>
              ))
            )}
          </div>

          {run.truncated ? (
            <p className={styles["absent"]} data-dfm-truncated="true">
              {copy.dfm.truncated}
            </p>
          ) : null}

          {run.errored_rules.length === 0 ? null : (
            <div className={styles["chips"]}>
              <span className={styles["rowName"]}>{copy.dfm.errored}</span>
              {run.errored_rules.map((rule) => (
                <span key={rule} className={styles["badge"]} data-dfm-errored-rule={rule}>
                  <Fact
                    source="dfm.last.errored_rules[]"
                    value={rule}
                    className={styles["mono"]}
                  />
                </span>
              ))}
              <p className={styles["note"]}>{copy.dfm.erroredNote}</p>
            </div>
          )}

          {run.findings.length === 0 ? (
            <p className={styles["absent"]}>{copy.dfm.clean}</p>
          ) : (
            <ul className={styles["list"]}>
              {run.findings.map((finding, index) => (
                <Finding
                  key={`${finding.rule_id}-${index}`}
                  finding={finding}
                  index={index}
                  source={source ?? "current"}
                  onResolve={
                    onResolveDescriptor === undefined
                      ? undefined
                      : (descriptor) => {
                          onResolveDescriptor({
                            part: dfm.part,
                            source_artifact_ref: finding.source_artifact_ref,
                            rule_id: finding.rule_id,
                            descriptor,
                          });
                        }
                  }
                />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}

export function DfmPanel({
  onResolveDescriptor,
}: {
  readonly onResolveDescriptor?: ((intent: DescriptorIntent) => void) | undefined;
}): React.JSX.Element {
  const part = useWorkspace((s) => s.part);
  const dfm = useDfm(part);
  const project = useProject();

  if (part === null) return <p className={styles["absent"]}>{copy.inspector.selectPart}</p>;
  if (dfm.data === undefined) return <p className={styles["absent"]}>{copy.absent.loading}</p>;
  return (
    <DfmView
      dfm={dfm.data}
      secureExecutor={project.data?.capabilities?.secure_executor}
      onResolveDescriptor={onResolveDescriptor}
    />
  );
}
