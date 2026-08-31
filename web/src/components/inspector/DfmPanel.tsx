// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `DfmPanel` — the manufacturability findings (INTERFACE.md §6.4, §4.7).
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
// THE TWO CONTROLS ARE NOT COLLAPSED. §6.4 splits the "DFM toggle" into (a) a
// **Run DFM** action (`POST /parts/{part}/dfm`) and (b) a project-settings write
// (`POST /project/config/dfm`), because `[dfm] auto_run` is a project setting
// and not a per-message flag. Both actions live here — the composer is for
// talking, and collapsing them into one switch would imply a tool argument
// that does not exist. The field list still *reads* `auto_run` as a project
// fact; the toggle *writes* it.
//
// §4.7's `Chip` CLAUSE, DISCHARGED. Line 225 used to render *"Automatic
// evaluation after each build: off"* as a chip in the panel's ACTION CORNER,
// looking exactly like a settings toggle — and the panel's prose then had to
// apologise underneath: *"This is a project setting in the manifest, not a
// per-message flag, and it is read-only here."* **When a layout has to be
// corrected by a caption, the layout is wrong.** The fact has moved into the
// `Field` list where every other read-only fact lives, and the caption is
// deleted. `Chip` renders a `<span>` and takes no `onClick`, so the arrangement
// cannot come back.
//
// `data-dfm-source` — §6.4 requires a finding on a transient preview and a
// finding on the current artifact to be *distinguishable in the panel*. The
// engine's `resolved_from` has three values and §6.4's attribute has two, so both
// are emitted: `data-dfm-resolved-from` carries the engine's word unrewritten,
// and `data-dfm-source` carries §6.4's `current` / `preview` distinction over it.

import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { WorkspaceError } from "../../api/client";
import { writeDfmAutoRun, runDfm } from "../../api/dfm";
import { uuid7 } from "../../api/idempotency";
import { keys, useDfm, useProject } from "../../api/queries";
import { refreshAfterTurn } from "../../api/refresh";
import type { DfmDocument, DfmFinding, DfmRun, TopologyDescriptor } from "../../api/types";
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
  SeverityBadge,
  formatValue,
  type Severity,
} from "../../system";
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
 * yet, and its request shapes do not accept a descriptor.** So the click emits
 * this intent and the workspace routes it to the Provenance panel, which renders
 * the artifact-bound address the finding carries and names the station of §4.3's
 * spine that is missing. It never fabricates a resolution.
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

/** §6.4's closed severity vocabulary, mapped onto the system's own (§4.7). */
function severityOf(value: string): Severity {
  return value === "error" || value === "warning" || value === "info" ? value : "info";
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
    <Button
      variant="quiet"
      title={copy.dfm.descriptorTitle}
      onClick={onResolve}
      data-dfm-descriptor={index}
      data-descriptor-kind={descriptor.kind}
      data-descriptor-solid={descriptor.solid_id}
      data-descriptor-index={descriptor.topology_index}
      data-descriptor-tag={descriptor.tag ?? ""}
    >
      <span className={styles["mono"]}>
        <Fact source="dfm.last.findings[].topology[].kind" value={descriptor.kind} />{" "}
        <Fact source="dfm.last.findings[].topology[].solid_id" value={descriptor.solid_id} />{" "}
        <Fact
          source="dfm.last.findings[].topology[].topology_index"
          value={descriptor.topology_index}
        />
        {descriptor.tag === null ? null : (
          <>
            {" "}
            <Fact source="dfm.last.findings[].topology[].tag" value={descriptor.tag} />
          </>
        )}
      </span>
    </Button>
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
        <SeverityBadge severity={severityOf(finding.severity)}>
          <Fact source="dfm.last.findings[].severity" value={finding.severity} />
        </SeverityBadge>
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

      <Fact
        source="dfm.last.findings[].message"
        value={finding.message}
        className={styles["findingMessage"]}
      />

      <div className={styles["chips"]}>
        <Chip data-finding-measured="">
          {copy.dfm.measured}:{" "}
          <Fact source="dfm.last.findings[].measured" value={measuredText(finding.measured)}>
            {formatValue(finding.measured)}
          </Fact>
        </Chip>
        {finding.suggested_bound === null ? null : (
          <Chip data-finding-bound="">
            {copy.dfm.suggested}:{" "}
            <Fact source="dfm.last.findings[].suggested_bound" value={finding.suggested_bound} />{" "}
            <Fact source="dfm.last.findings[].bound_unit" value={finding.bound_unit} />
          </Chip>
        )}
        {finding.tags.map((tag) => (
          <Chip key={tag} tone="code" data-dfm-tag={tag}>
            <Fact source="dfm.last.findings[].tags[]" value={tag} />
          </Chip>
        ))}
      </div>

      <div className={styles["chips"]}>
        <span className={styles["muted"]}>{copy.dfm.topology}</span>
        {finding.topology.map((descriptor, descriptorIndex) => (
          <Descriptor
            key={`${descriptor.kind}-${String(descriptor.solid_id)}-${String(descriptor.topology_index)}`}
            descriptor={descriptor}
            index={descriptorIndex}
            onResolve={onResolve === undefined ? undefined : () => onResolve(descriptor)}
          />
        ))}
      </div>
    </li>
  );
}

/** The two §6.4 write actions — never collapsed into one switch. */
export function DfmActions({
  dfm,
  onToggleAutoRun,
  onRunDfm,
  busy,
  error,
}: {
  readonly dfm: DfmDocument;
  readonly onToggleAutoRun?: (() => void) | undefined;
  readonly onRunDfm?: (() => void) | undefined;
  readonly busy?: "auto_run" | "run" | null | undefined;
  readonly error?: string | null | undefined;
}): React.JSX.Element {
  return (
    <div className={styles["dfmActions"]} data-composer-dfm="">
      <Button
        variant="toggle"
        pressed={dfm.auto_run}
        onClick={onToggleAutoRun}
        data-dfm-auto-run={String(dfm.auto_run)}
        data-dfm-auto-run-toggle=""
        {...(busy !== null && busy !== undefined
          ? { disabled: true as const, reason: copy.composer.dfmWriting }
          : {})}
      >
        {copy.composer.dfmAutoRun}
      </Button>
      <Button
        variant="quiet"
        onClick={onRunDfm}
        data-dfm-run=""
        {...(busy !== null && busy !== undefined
          ? { disabled: true as const, reason: copy.composer.dfmRunning }
          : {})}
      >
        {copy.composer.dfmRun}
      </Button>
      {error !== null && error !== undefined ? (
        <p className={styles["muted"]} data-composer-dfm-error="">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export interface DfmViewProps {
  readonly dfm: DfmDocument;
  readonly onToggleAutoRun?: (() => void) | undefined;
  readonly onRunDfm?: (() => void) | undefined;
  readonly dfmBusy?: "auto_run" | "run" | null | undefined;
  readonly dfmError?: string | null | undefined;
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
  onToggleAutoRun,
  onRunDfm,
  dfmBusy,
  dfmError,
}: DfmViewProps): React.JSX.Element {
  const run = dfm.last;
  const source = run === null ? null : dfmSource(run);
  const severities = run === null ? [] : Object.keys(run.severity_counts).sort();

  return (
    <Panel
      label={copy.dfm.heading}
      data-panel="dfm"
      data-dfm-source={source ?? ""}
      data-dfm-resolved-from={dfm.resolved_from ?? ""}
    >
      <PanelHeader title={copy.dfm.heading} level={3} />
      <PanelBody>
        <DfmActions
          dfm={dfm}
          onToggleAutoRun={onToggleAutoRun}
          onRunDfm={onRunDfm}
          busy={dfmBusy}
          error={dfmError}
        />
        {run === null ? (
          <EmptyState
            icon={secureExecutor === false ? "alert" : "plane"}
            title={secureExecutor === false ? copy.dfm.capabilityTitle : copy.dfm.absentTitle}
            body={secureExecutor === false ? copy.dfm.capabilityRefused : copy.dfm.absent}
            data-dfm-absence={secureExecutor === false ? "capability" : "no_run"}
          />
        ) : (
          <>
            <DataTable
              rows={[
                {
                  key: "resolved",
                  label: copy.dfm.resolvedFrom,
                  value: (
                    <Fact source="dfm.last.resolved_from" value={run.resolved_from}>
                      {copy.dfm.resolved[run.resolved_from]}
                    </Fact>
                  ),
                  note: (
                    <Fact
                      source="dfm.last.source_artifact_ref"
                      value={run.source_artifact_ref}
                      mono
                    />
                  ),
                  attrs: { "data-dfm-resolved-from": run.resolved_from },
                },
                {
                  key: "process",
                  label: copy.dfm.process,
                  value: <Fact source="dfm.last.process" value={run.process} />,
                },
                {
                  key: "pack",
                  label: copy.dfm.pack,
                  value: (
                    <>
                      <Fact source="dfm.last.pack.name" value={run.pack.name} />{" "}
                      <Fact source="dfm.last.pack.version" value={run.pack.version} />
                    </>
                  ),
                },
                {
                  key: "registry",
                  label: copy.dfm.registry,
                  value: <Fact source="dfm.last.pack.registry" value={run.pack.registry} />,
                  note: (
                    <Fact
                      source="dfm.last.pack.registry_digest"
                      value={run.pack.registry_digest}
                      mono
                    />
                  ),
                },
                {
                  key: "material",
                  label: copy.dfm.material,
                  value:
                    run.material === null ? (
                      <span className={styles["muted"]}>{copy.absent.unavailable}</span>
                    ) : (
                      <Fact
                        source="dfm.last.material.name"
                        value={String(run.material["name"] ?? "")}
                      />
                    ),
                },
                {
                  // §4.7: this is a READ-ONLY PROJECT FACT and it lives in the
                  // field list with every other one. It was a chip in the action
                  // corner with an apologetic caption underneath.
                  key: "auto_run",
                  label: copy.dfm.autoRun,
                  value: (
                    <Fact source="dfm.auto_run" value={dfm.auto_run}>
                      {dfm.auto_run ? copy.dfm.autoRunOn : copy.dfm.autoRunOff}
                    </Fact>
                  ),
                  attrs: { "data-dfm-auto-run": String(dfm.auto_run) },
                },
              ]}
            />

            <PanelSection eyebrow={copy.dfm.severity}>
              <div className={styles["chips"]}>
                {severities.length === 0 ? (
                  <Chip data-dfm-clean="">{copy.dfm.clean}</Chip>
                ) : (
                  severities.map((severity) => (
                    <SeverityBadge key={severity} severity={severityOf(severity)}>
                      {severity}:{" "}
                      <Fact
                        source="dfm.last.severity_counts[]"
                        value={run.severity_counts[severity] ?? null}
                      />
                    </SeverityBadge>
                  ))
                )}
              </div>
            </PanelSection>

            {run.truncated ? (
              <PanelNote data-dfm-truncated="true">{copy.dfm.truncated}</PanelNote>
            ) : null}

            {run.errored_rules.length === 0 ? null : (
              <PanelSection eyebrow={copy.dfm.errored}>
                <div className={styles["chips"]}>
                  {run.errored_rules.map((rule) => (
                    <SeverityBadge key={rule} severity="warning" data-dfm-errored-rule={rule}>
                      <Fact source="dfm.last.errored_rules[]" value={rule} />
                    </SeverityBadge>
                  ))}
                </div>
                <PanelNote>{copy.dfm.erroredNote}</PanelNote>
              </PanelSection>
            )}

            {run.findings.length === 0 ? (
              <EmptyState icon="check" title={copy.dfm.cleanTitle} body={copy.dfm.clean} />
            ) : (
              <ul className={styles["list"]}>
                {run.findings.map((finding, index) => (
                  <Finding
                    key={`${finding.rule_id}-${String(index)}`}
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
      </PanelBody>
    </Panel>
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
  const client = useQueryClient();
  const [dfmBusy, setDfmBusy] = useState<"auto_run" | "run" | null>(null);
  const [dfmError, setDfmError] = useState<string | null>(null);

  const toggleAutoRun = useCallback(() => {
    if (dfm.data === undefined || dfmBusy !== null) return;
    setDfmBusy("auto_run");
    setDfmError(null);
    void writeDfmAutoRun(!dfm.data.auto_run, uuid7())
      .then(() => {
        if (part !== null) {
          void client.invalidateQueries({ queryKey: keys.dfm(part) });
        }
      })
      .catch((cause: unknown) => {
        setDfmError(cause instanceof WorkspaceError ? cause.message : copy.composer.dfmWriting);
      })
      .finally(() => {
        setDfmBusy(null);
      });
  }, [client, dfm.data, dfmBusy, part]);

  const runDfmNow = useCallback(() => {
    if (part === null || dfmBusy !== null) return;
    setDfmBusy("run");
    setDfmError(null);
    void runDfm(part, uuid7())
      .then(() => {
        refreshAfterTurn(client, part);
      })
      .catch((cause: unknown) => {
        setDfmError(cause instanceof WorkspaceError ? cause.message : copy.composer.dfmRunning);
      })
      .finally(() => {
        setDfmBusy(null);
      });
  }, [client, dfmBusy, part]);

  if (part === null) {
    return <EmptyState icon="cube" title={copy.inspector.noPartTitle} body={copy.inspector.selectPart} />;
  }
  if (dfm.data === undefined) return <PanelNote>{copy.absent.loading}</PanelNote>;
  return (
    <DfmView
      dfm={dfm.data}
      secureExecutor={project.data?.capabilities?.secure_executor}
      onResolveDescriptor={onResolveDescriptor}
      onToggleAutoRun={toggleAutoRun}
      onRunDfm={runDfmNow}
      dfmBusy={dfmBusy}
      dfmError={dfmError}
    />
  );
}
