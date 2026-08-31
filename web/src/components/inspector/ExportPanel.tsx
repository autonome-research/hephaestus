// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `ExportPanel` — the Inspector's sixth tab (INTERFACE.md §22.7, §4.7).
//
// THE SUBJECT COMES BEFORE THE CONTROLS. §22.7's TIGHTENING: "`ExportPanel` is
// the only Inspector tab containing a control that writes, so it renders its
// **subject before its controls**: the pinned ref, its `pin_mode`, and the part,
// on the first line, above any format button. There is no bare 'Export ▾' that
// resolves its subject at click time." That is not a layout preference — it is
// §22.5's decision made visible. The request carries
// `WorkspaceState.artifact_ref` verbatim, never `null` and never "current", so
// the file is the geometry on screen rather than whatever published in between.
//
// TWO STEPS, NOT ONE. **Export** runs the keyed mutation; **Download** fetches
// the bytes. §22.7: "They are two routes with two failure modes, and a single
// button would report a create-only refusal and a transfer failure with the same
// spinner." The Download buttons therefore live in the history, one per output,
// where they are addressed by a blob the server named and labelled with a
// filename the server derived (§22.4 — the client re-derives neither).
//
// THE KEY IS THE PANEL'S. §22.2's TIGHTENING binds this component specifically:
// "the key is minted once per *submission*, not once per click: the client reuses
// it across transport retries of one export and mints a fresh UUIDv7 the moment
// any field changes. A stale key with a changed format is `key_payload_mismatch`;
// a fresh key with unchanged fields silently produces a second identical file.
// Both are wrong and both are the client's to prevent, so the panel owns the key
// and the retry button does not re-mint."
//
// The second half of that sentence is understated and this panel says so: for the
// four byte-deterministic formats a fresh key with unchanged fields does not
// produce a second file, it produces `target_exists`, because the no-target stem
// is content-addressed. So the key is derived from the *submission fields* — one
// key per distinct field set — which makes the unchanged resubmission a ledger
// replay by construction rather than by remembering not to re-mint.
//
// NO KERF CONTROL, AND THE PANEL SAYS WHY (§22.1). The resolved decision is
// displayed — `applied_mm`, `source`, `process` — and `kerf_uncompensated` is
// rendered as a warning **on the produced file**, not as a refusal: the file is
// correct, it is just nominal.
//
// NO UNPIN, NO DELETE, AND THE PANEL SAYS SO (§22.6). `unpin_available` is a
// server field, so the sentence is a fact the client renders rather than a policy
// it asserts.
//
// §4.7's last line: this component declares no colour, type or border of its own.

import { useCallback, useMemo, useState } from "react";
import {
  DOC_KINDS,
  DRAWING_KINDS,
  DRAWING_SHEETS,
  EXPORT_FORMATS,
  EXPORT_LAYOUTS,
  EXPORT_SUBJECTS,
  LAYOUT_FORMATS,
  downloadExport,
  runDoc,
  runDrawing,
  runExport,
  submissionKey,
  tooLargeToBuffer,
  type DocKind,
  type DrawingKind,
  type DrawingSheet,
  type ExportFormat,
  type ExportLayout,
  type ExportOutput,
  type ExportResult,
  type ExportRow,
  type ExportState,
  type ExportSubject,
  type ExportsDocument,
  type KerfDecision,
} from "../../api/exports";
import { WorkspaceError } from "../../api/client";
import { keys, useExports } from "../../api/queries";
import { useQueryClient } from "@tanstack/react-query";
import { copy } from "../../copy";
import { useWorkspace } from "../../state/react";
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
  Select,
  TextInput,
  formatBytes,
  formatRef,
  type DataRow,
} from "../../system";
import { Fact } from "../Fact";
import styles from "./ExportPanel.module.css";

/**
 * Why the controls are disabled, when they are — §22.7's refusal table, decided
 * **before** a request rather than after one.
 *
 * Closed, and each value is either an engine reason or the absence of a subject.
 * §22.7: "the controls are disabled with the checkpoint or addressing reason
 * above and the panel names the build error rather than rendering an enabled
 * button that will 4xx".
 */
export const EXPORT_BLOCKERS = ["no_part", "no_pin", "invalid_source"] as const;
export type ExportBlocker = (typeof EXPORT_BLOCKERS)[number];

/** The submission fields, from which the idempotency key is derived (§22.2). */
export interface Submission {
  readonly subject: ExportSubject;
  readonly format: ExportFormat;
  readonly layout: ExportLayout;
  readonly blankWidth: string;
  readonly blankHeight: string;
  readonly drawingKind: DrawingKind;
  readonly sheet: DrawingSheet;
  readonly docKind: DocKind;
  readonly artifactRef: string | null;
}

const INITIAL: Omit<Submission, "artifactRef"> = {
  subject: "export",
  format: "step",
  layout: "as_built",
  blankWidth: "",
  blankHeight: "",
  drawingKind: "dimensioned",
  sheet: "A4",
  docKind: "bom",
};

/**
 * The signature §22.2 keys on: a fresh key the moment any field changes, and the
 * same key for every retry of one unchanged submission.
 *
 * The artifact ref is in the signature because it is a field of the request —
 * exporting the same format from a different pin is a different submission, and
 * reusing the key across the two would be `key_payload_mismatch` by the server's
 * own reckoning.
 */
function signature(submission: Submission): string {
  const parts: readonly string[] =
    submission.subject === "export"
      ? [submission.format, submission.layout, submission.blankWidth, submission.blankHeight]
      : submission.subject === "drawing"
        ? [submission.drawingKind, submission.sheet]
        : [submission.docKind];
  return [submission.subject, submission.artifactRef ?? "", ...parts].join("|");
}

/** The kind segment of an artifact ref — the only thing this panel reads off one. */
function refKind(ref: string): string {
  const parts = ref.split(":");
  return parts.length === 4 && parts[0] === "artifact" ? (parts[1] ?? "") : "";
}

/**
 * Whether the pinned artifact can be exported at all, and why not.
 *
 * The one check the client makes ahead of the server, and it is admissible
 * because it reads nothing the server would have to compute: `artifact:<kind>:…`
 * is the ref's own grammar, and `_freeze_export_source` refuses any kind but
 * `build` by that same segment. §22.7 asks for exactly this — a disabled control
 * that states its reason beats an enabled one that 4xxes.
 */
export function exportBlocker(part: string | null, pinned: string | null): ExportBlocker | null {
  if (part === null) return "no_part";
  if (pinned === null) return "no_pin";
  return refKind(pinned) === "build" ? null : "invalid_source";
}

/** A named refusal reason, or `run_failed` for anything without one. */
function refusalKey(error: unknown): keyof typeof copy.export.refusals {
  const reason = error instanceof WorkspaceError ? error.reason : "";
  return reason in copy.export.refusals
    ? (reason as keyof typeof copy.export.refusals)
    : "run_failed";
}

/**
 * The key for one submission, stable across retries of that submission.
 *
 * Module-scoped rather than component state so a remount — switching Inspector
 * tabs, which unmounts this panel — does not re-mint a key for a submission the
 * operator has already sent. Remounting and then clicking Export again is
 * precisely the "transport retry" §22.2 wants replayed, and a per-component map
 * would execute it a second time instead.
 */
const SUBMISSION_KEYS = new Map<string, string>();

export function submissionKeyFor(submission: Submission): string {
  const id = signature(submission);
  const existing = SUBMISSION_KEYS.get(id);
  if (existing !== undefined) return existing;
  const minted = submissionKey();
  SUBMISSION_KEYS.set(id, minted);
  return minted;
}

/** Test seam: forget every minted key (a fresh workspace, a fresh test). */
export function resetSubmissionKeys(): void {
  SUBMISSION_KEYS.clear();
}

export interface ExportViewProps {
  readonly part: string | null;
  readonly pinned: string | null;
  readonly pinMode: "current" | "pinned";
  /** `GET /parts/{part}/exports`, when it has answered. */
  readonly history?: ExportsDocument | undefined;
  /**
   * §22.7: a *stale* part is not a refusal — the pin is exported and the subject
   * line says the build is behind the script.
   *
   * **DEVIATION, LOUD, and the reason this prop has no producer.** No route on
   * §2.3's table serves a staleness fact for a part. The engine has one —
   * `publisher.projections.state().stale` is what `_freeze_export_source` reads
   * on the null-ref branch — and neither `GET /parts` nor `GET /parts/{part}/
   * build` projects it (`build_projection` serves `current`, which is a different
   * fact: whether this build is the part's latest, not whether the *script* has
   * moved past it). The sentence §22.7 requires therefore has nothing true to
   * render, and the panel does not invent one: deriving staleness client-side by
   * comparing `PartSummary.content_hash` against the build's script input hash is
   * exactly the derived fact §1 forbids. The prop and its copy exist so the
   * designed state is built and tested; wiring it needs a `stale` field on the
   * build projection, which is new work.
   */
  readonly stale?: boolean | undefined;
  readonly onExport: (submission: Submission) => Promise<ExportResult>;
  readonly onDownload: (output: ExportOutput) => Promise<void>;
}

export function ExportView(props: ExportViewProps): React.JSX.Element {
  const { part, pinned, pinMode, history, stale, onExport, onDownload } = props;
  const [fields, setFields] = useState(INITIAL);
  const [state, setState] = useState<ExportState>("idle");
  const [result, setResult] = useState<ExportResult | null>(null);
  const [refusal, setRefusal] = useState<keyof typeof copy.export.refusals | null>(null);
  const [downloadRefusal, setDownloadRefusal] = useState<
    keyof typeof copy.export.refusals | null
  >(null);

  const submission: Submission = { ...fields, artifactRef: pinned };
  // One key per distinct field set (§22.2's TIGHTENING), minted by the same
  // function the request uses so the attribute a test reads and the header the
  // server receives cannot be two different keys.
  const idempotencyKey = submissionKeyFor(submission);

  const blocker = exportBlocker(part, pinned);
  const blockerReason =
    blocker === "no_part"
      ? copy.export.noPart
      : blocker === "no_pin"
        ? copy.export.noPin
        : blocker === "invalid_source"
          ? copy.export.refusals.invalid_source
          : null;

  const layoutOffered =
    fields.subject === "export" && (LAYOUT_FORMATS as readonly string[]).includes(fields.format);
  const blankOffered = layoutOffered && fields.layout === "nested_sheet";

  // Deliberately not memoized: it closes over `submission`, which is rebuilt
  // from the field state on every render, so a `useCallback` over it would be a
  // dependency list that changes every render — the memo with none of the
  // benefit. Nothing downstream is memoized on this identity.
  const run = (): void => {
    setState("exporting");
    setRefusal(null);
    void onExport(submission)
      .then((document) => {
        setResult(document);
        setState("idle");
      })
      .catch((error: unknown) => {
        setRefusal(refusalKey(error));
        setState("refused");
      });
  };

  const download = useCallback(
    (output: ExportOutput) => {
      setState("transferring");
      setDownloadRefusal(null);
      void onDownload(output)
        .then(() => {
          setState("idle");
        })
        .catch((error: unknown) => {
          setDownloadRefusal(refusalKey(error));
          setState("refused");
        });
    },
    [onDownload],
  );

  return (
    <Panel
      label={copy.export.heading}
      data-panel="export"
      data-export-state={state}
      data-export-blocked={blocker ?? ""}
    >
      <PanelHeader
        title={copy.export.heading}
        level={3}
        actions={
          history === undefined ? undefined : (
            <Chip data-export-total={String(history.total_bytes)}>
              {`${copy.export.historyTotal} ${formatBytes(history.total_bytes)}`}
            </Chip>
          )
        }
      />
      <PanelBody>
        {/* §22.7's TIGHTENING — the subject, above any control. */}
        <PanelSection eyebrow={copy.export.subjectHeading}>
          <DataTable
            rows={[
              {
                key: "part",
                label: copy.export.part,
                value:
                  part === null ? (
                    <span className={styles["muted"]}>{copy.export.noPart}</span>
                  ) : (
                    <Fact source="workspace.part" value={part} />
                  ),
              },
              {
                key: "artifact",
                label: copy.export.pinned,
                value:
                  pinned === null ? (
                    <span className={styles["muted"]}>{copy.export.noPin}</span>
                  ) : (
                    <Fact source="workspace.artifact_ref" value={pinned} mono>
                      {formatRef(pinned)}
                    </Fact>
                  ),
                note: copy.export.pinMode[pinMode],
                attrs: { "data-export-pin-mode": pinMode },
              },
            ]}
          />
          <PanelNote className={styles["span"]}>{copy.export.subjectNote}</PanelNote>
          {stale === true ? (
            <PanelNote className={styles["span"]} data-export-stale="true">
              {copy.export.staleNote}
            </PanelNote>
          ) : null}
        </PanelSection>

        {blockerReason === null ? null : (
          <PanelNote data-export-refusal={blocker ?? ""}>{blockerReason}</PanelNote>
        )}

        <PanelSection eyebrow={copy.export.subjectKinds[fields.subject]}>
          <div className={styles["controls"]}>
            <Select
              label={copy.export.subjectHeading}
              value={fields.subject}
              options={[...EXPORT_SUBJECTS]}
              onChange={(next) => {
                setFields({ ...fields, subject: next as ExportSubject });
              }}
              data-export-subject={fields.subject}
            />

            {fields.subject === "export" ? (
              <div className={styles["formats"]} role="group" aria-label={copy.export.format}>
                {EXPORT_FORMATS.map((format) => (
                  <Button
                    key={format}
                    variant="toggle"
                    pressed={fields.format === format}
                    data-export-format={format}
                    onClick={() => {
                      setFields({
                        ...fields,
                        format,
                        // A layout the new format cannot take is not carried
                        // forward: the tool's conditional would refuse it, and a
                        // control that exists only to produce `invalid_params`
                        // is a trap (§22.1).
                        layout: (LAYOUT_FORMATS as readonly string[]).includes(format)
                          ? fields.layout
                          : "as_built",
                      });
                    }}
                  >
                    {format}
                  </Button>
                ))}
              </div>
            ) : null}

            {layoutOffered ? (
              <Select
                label={copy.export.layout}
                value={fields.layout}
                options={[...EXPORT_LAYOUTS]}
                onChange={(next) => {
                  setFields({ ...fields, layout: next as ExportLayout });
                }}
                data-export-layout={fields.layout}
              />
            ) : null}

            {fields.subject === "drawing" ? (
              <>
                <Select
                  label={copy.export.drawingKind}
                  value={fields.drawingKind}
                  options={[...DRAWING_KINDS]}
                  onChange={(next) => {
                    setFields({ ...fields, drawingKind: next as DrawingKind });
                  }}
                  data-export-drawing-kind={fields.drawingKind}
                />
                <Select
                  label={copy.export.sheet}
                  value={fields.sheet}
                  options={[...DRAWING_SHEETS]}
                  onChange={(next) => {
                    setFields({ ...fields, sheet: next as DrawingSheet });
                  }}
                  data-export-sheet={fields.sheet}
                />
              </>
            ) : null}

            {fields.subject === "doc" ? (
              <Select
                label={copy.export.docKind}
                value={fields.docKind}
                options={[...DOC_KINDS]}
                onChange={(next) => {
                  setFields({ ...fields, docKind: next as DocKind });
                }}
                data-export-doc-kind={fields.docKind}
              />
            ) : null}
          </div>

          {blankOffered ? (
            <div className={styles["blank"]} data-export-blank="true">
              <TextInput
                label={copy.export.blankWidth}
                value={fields.blankWidth}
                onChange={(next) => {
                  setFields({ ...fields, blankWidth: next });
                }}
                data-export-blank-width=""
              />
              <TextInput
                label={copy.export.blankHeight}
                value={fields.blankHeight}
                onChange={(next) => {
                  setFields({ ...fields, blankHeight: next });
                }}
                data-export-blank-height=""
              />
            </div>
          ) : null}

          {layoutOffered ? (
            <PanelNote className={styles["span"]}>{copy.export.layoutNote}</PanelNote>
          ) : null}

          <div className={styles["actions"]}>
            <Button
              variant="primary"
              icon="download"
              data-export-run=""
              data-export-key={idempotencyKey}
              {...(blockerReason !== null
                ? { disabled: true as const, reason: blockerReason }
                : state === "exporting"
                  ? { disabled: true as const, reason: copy.export.running }
                  : { onClick: run })}
            >
              {state === "exporting" ? copy.export.running : copy.export.run}
            </Button>
          </div>
          <PanelNote className={styles["span"]}>{copy.export.twoSteps}</PanelNote>
        </PanelSection>

        {refusal === null ? null : (
          <PanelSection eyebrow={copy.export.refusalHeading}>
            <PanelNote className={styles["span"]} data-export-refusal={refusal}>
              {copy.export.refusals[refusal]}
            </PanelNote>
          </PanelSection>
        )}

        {result?.kerf === undefined ? null : <Kerf kerf={result.kerf} />}

        <PanelSection eyebrow={copy.export.historyHeading}>
          {history === undefined || history.exports.length === 0 ? (
            <EmptyState
              icon="download"
              title={copy.export.historyEmpty}
              body={<p>{copy.export.retentionWhy}</p>}
              density="inline"
            />
          ) : (
            <ul className={styles["history"]}>
              {history.exports.map((row) => (
                <HistoryEntry
                  key={row.op_id}
                  row={row}
                  history={history}
                  onDownload={download}
                  transferring={state === "transferring"}
                />
              ))}
            </ul>
          )}
          {downloadRefusal === null ? null : (
            <PanelNote className={styles["span"]} data-export-download-refusal={downloadRefusal}>
              {copy.export.refusals[downloadRefusal]}
            </PanelNote>
          )}
          {history?.unpin_available === false ? (
            <PanelNote className={styles["span"]} data-export-unpin="unavailable">
              {copy.export.retention}
            </PanelNote>
          ) : null}
        </PanelSection>
      </PanelBody>
    </Panel>
  );
}

/** §22.1: the panel *displays* the resolved kerf and never offers to set one. */
function Kerf({ kerf }: { readonly kerf: KerfDecision }): React.JSX.Element {
  const uncompensated = kerf.applied_mm === null;
  const source = kerf.source in copy.export.kerfSources ? kerf.source : null;
  const rows: readonly DataRow[] = [
    {
      key: "applied",
      label: copy.export.kerfApplied,
      value: <Fact source="export.kerf.applied_mm" value={kerf.applied_mm} />,
      unit: kerf.applied_mm === null ? undefined : "mm",
    },
    {
      key: "source",
      label: copy.export.kerfSource,
      value: <Fact source="export.kerf.source" value={kerf.source} />,
      note:
        source === null
          ? undefined
          : copy.export.kerfSources[source as keyof typeof copy.export.kerfSources],
    },
    {
      key: "process",
      label: copy.export.kerfProcess,
      value: <Fact source="export.kerf.process" value={kerf.process} />,
    },
  ];
  return (
    <PanelSection eyebrow={copy.export.kerfHeading}>
      {/* The attributes ride CHIPS rather than a wrapper `<div>`: a wrapper
          between `PanelSection` and `DataTable` breaks the table's `subgrid`,
          which is the alignment §4.7 declares once per panel. */}
      <div className={styles["chips"]}>
        <Chip data-export-kerf={kerf.source}>{kerf.source}</Chip>
        {kerf.note === undefined ? null : (
          <Chip data-export-kerf-note={kerf.note}>{kerf.note}</Chip>
        )}
      </div>
      <DataTable rows={rows} />
      {uncompensated ? (
        <PanelNote className={styles["span"]} data-export-warning="kerf_uncompensated">
          {copy.export.kerfUncompensated}
        </PanelNote>
      ) : null}
      <PanelNote className={styles["span"]}>{copy.export.kerfNotBrowser}</PanelNote>
    </PanelSection>
  );
}

/**
 * One committed export in the history (§22.6's visible retention).
 *
 * Every string here is the server's: the filename it derived, the byte count it
 * measured, the recorded path it stored. §22.4's TIGHTENING is the reason the
 * byte count is rendered *before* the button rather than beside a spinner — "a
 * large file is a stated cost and not a hang".
 */
function HistoryEntry({
  row,
  history,
  onDownload,
  transferring,
}: {
  readonly row: ExportRow;
  readonly history: ExportsDocument;
  readonly onDownload: (output: ExportOutput) => void;
  readonly transferring: boolean;
}): React.JSX.Element {
  return (
    <li className={styles["entry"]} data-export-row={row.op_id} data-export-format={row.format}>
      <div className={styles["entryHead"]}>
        <Chip tone="code" data-export-row-format={row.format}>
          {row.format}
        </Chip>
        <Chip data-export-row-layout={row.layout}>{row.layout}</Chip>
        <Chip data-export-row-bytes={String(row.total_bytes)}>{formatBytes(row.total_bytes)}</Chip>
      </div>
      {/* A plain labelled line, not a `DataTable`: the table's three tracks are
          `subgrid` over the panel body, and this `<li>` is a flex column — a
          table here would silently fall back to one column and stack its label
          under its value. One fact needs no table. */}
      <div className={styles["file"]}>
        <span className={styles["muted"]}>{copy.export.source}</span>
        <Fact
          source="exports[].source_artifact_ref"
          value={row.source_artifact_ref}
          className={styles["mono"]}
        >
          {formatRef(row.source_artifact_ref)}
        </Fact>
      </div>
      {row.outputs.map((output) => {
        const tooLarge = tooLargeToBuffer(output, history);
        return (
          <div className={styles["file"]} key={output.blob} data-export-file={output.blob}>
            {/* The recorded path renders as body text — §22.3: it is where a
                quote is harmless, unlike the header the filename rides in. */}
            <span className={styles["fileName"]} data-export-path={output.path}>
              {output.path}
            </span>
            <Fact
              source="exports[].outputs[].bytes"
              value={output.bytes}
              className={styles["muted"]}
            >
              {formatBytes(output.bytes)}
            </Fact>
            <Button
              variant="secondary"
              icon="download"
              data-export-download={output.blob}
              data-export-filename={output.filename}
              {...(tooLarge
                ? { disabled: true as const, reason: copy.export.refusals.export_too_large }
                : transferring
                  ? { disabled: true as const, reason: copy.export.downloading }
                  : {
                      onClick: () => {
                        onDownload(output);
                      },
                    })}
            >
              {tooLarge ? copy.export.tooLarge : copy.export.download}
            </Button>
          </div>
        );
      })}
    </li>
  );
}

/**
 * The pin-bound export actions. Shared by the inspector tab and the header
 * chrome so both send the same `artifact_ref` and mint keys the same way.
 *
 * The history is invalidated on a committed export and at no other time: it is
 * the record of a retention obligation, and this client is the only thing that
 * can change it from here.
 */
export function useExportActions(): {
  readonly part: string | null;
  readonly pinned: string | null;
  readonly pinMode: "current" | "pinned";
  readonly history: ExportsDocument | undefined;
  readonly onExport: (submission: Submission) => Promise<ExportResult>;
  readonly onDownload: (output: ExportOutput) => Promise<void>;
} {
  const part = useWorkspace((s) => s.part);
  const pinned = useWorkspace((s) => s.artifact_ref);
  const pinMode = useWorkspace((s) => s.pin_mode);
  const history = useExports(part);
  const client = useQueryClient();

  const onExport = useMemo(
    () =>
      async (submission: Submission): Promise<ExportResult> => {
        if (part === null || submission.artifactRef === null) {
          // Unreachable: the button is disabled with a reason in both states.
          throw new WorkspaceError(400, "invalid_params", copy.export.noPin);
        }
        const artifact_ref = submission.artifactRef;
        const key = submissionKeyFor(submission);
        const result =
          submission.subject === "export"
            ? await runExport(
                part,
                {
                  artifact_ref,
                  format: submission.format,
                  layout: submission.layout,
                  ...(submission.layout === "nested_sheet" &&
                  submission.blankWidth !== "" &&
                  submission.blankHeight !== ""
                    ? {
                        blank: {
                          width_mm: Number(submission.blankWidth),
                          height_mm: Number(submission.blankHeight),
                        },
                      }
                    : {}),
                },
                key,
              )
            : submission.subject === "drawing"
              ? await runDrawing(
                  part,
                  { artifact_ref, kind: submission.drawingKind, sheet: submission.sheet },
                  key,
                )
              : await runDoc(part, { artifact_ref, kind: submission.docKind }, key);
        await client.invalidateQueries({ queryKey: keys.exports(part) });
        return result;
      },
    [client, part],
  );

  return { part, pinned, pinMode, history: history.data, onExport, onDownload: downloadExport };
}

/** The inspector tab, bound to the workspace pin. */
export function ExportPanel(): React.JSX.Element {
  const { part, pinned, pinMode, history, onExport, onDownload } = useExportActions();
  return (
    <ExportView
      part={part}
      pinned={pinned}
      pinMode={pinMode}
      history={history}
      onExport={onExport}
      onDownload={onDownload}
    />
  );
}
