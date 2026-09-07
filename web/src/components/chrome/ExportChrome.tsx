// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Compact export control for header chrome. Bound to the workspace pin
// (INTERFACE.md §22.5): the request carries `WorkspaceState.artifact_ref`
// verbatim. Formats, blockers, and the submission key are the same ones the
// inspector tab uses — AND SO IS THE STATE MACHINE
// (`components/export/submission.ts`). This is not a second exporter, and until
// J-web-stream-11 it was: the two components held identical `useState` and ran
// hand-copied transitions that had already diverged, with this one's `run`
// clearing the previous result and the panel's not. The markup below is all
// that is this component's own.
//
// TWO STEPS IN THIS DIALOG (#77, after #100). Export runs the keyed mutation.
// Download fetches the bytes (`downloadExport`) with the byte count stated
// before the button (§22.4). `icon="download"` is the second step; the first
// step must not wear it. History stays on the inspector tab.
//
// Drawings, documents, nested-sheet blanks, and kerf readout stay on the
// inspector Export tab. Chrome is the simple "take this geometry out" path:
// six formats, as-built, produce, then give.

import { useState } from "react";
import {
  EXPORT_FORMATS,
  type ExportFormat,
  type ExportOutput,
  type ExportResult,
  type ExportRow,
  type ExportsDocument,
} from "../../api/exports";
import { copy } from "../../copy";
import {
  Button,
  Panel,
  PanelBody,
  PanelHeader,
  PanelNote,
  formatBytes,
  formatRef,
} from "../../system";
import { Fact } from "../Fact";
import {
  blockerReasonText,
  exportBlocker,
  submissionKeyFor,
  useExportSubmission,
  type Submission,
} from "../export/submission";
import styles from "./PartChrome.module.css";

const CHROME_SUBMISSION = {
  subject: "export",
  layout: "as_built",
  blankWidth: "",
  blankHeight: "",
  drawingKind: "dimensioned",
  sheet: "A4",
  docKind: "bom",
} as const;

export interface ExportChromeProps {
  readonly part: string | null;
  readonly pinned: string | null;
  readonly pinMode: "current" | "pinned";
  readonly history?: ExportsDocument | undefined;
  readonly onExport: (submission: Submission) => Promise<ExportResult>;
  readonly onDownload: (output: ExportOutput) => Promise<void>;
  readonly onOpenInspector: () => void;
}

/**
 * The committed row this dialog just produced, matched from the history the
 * inspector already owns. Bytes and filename are server fields (§22.4); the
 * result document names the hashes, not the download address.
 */
export function producedRow(
  history: ExportsDocument | undefined,
  result: ExportResult | null,
  format: ExportFormat,
): ExportRow | null {
  if (history === undefined || result === null) return null;
  for (let i = history.exports.length - 1; i >= 0; i -= 1) {
    const row = history.exports[i];
    if (row === undefined) continue;
    if (
      row.state === "COMMITTED" &&
      row.format === format &&
      row.source_artifact_ref === result.source_artifact_ref
    ) {
      return row;
    }
  }
  return null;
}

export function ExportChrome(props: ExportChromeProps): React.JSX.Element {
  const { part, pinned, pinMode, history, onExport, onDownload, onOpenInspector } = props;
  const [format, setFormat] = useState<ExportFormat>("step");
  // The SAME state machine the Inspector tab runs (J-web-stream-11). This
  // component's two `catch` blocks used to inline, byte for byte, the body of a
  // helper the panel declared without an export — one mapping in three copies —
  // and its `run` had a clear the panel's did not, which is how the two drifted.
  const { state, result, refusal, downloadRefusal, run, download, reset } = useExportSubmission(
    onExport,
    onDownload,
  );

  const submission: Submission = { ...CHROME_SUBMISSION, format, artifactRef: pinned, part };
  const idempotencyKey = submissionKeyFor(submission);
  const blocker = exportBlocker(part, pinned);
  const blockerReason = blockerReasonText(blocker);
  const row = producedRow(history, result, format);

  return (
    <Panel
      label={copy.chrome.export}
      data-panel="export-chrome"
      data-export-state={state}
      data-export-blocked={blocker ?? ""}
    >
      <PanelHeader title={copy.chrome.export} level={3} />
      <PanelBody>
        <div className={styles["subject"]} data-export-pin-mode={pinMode}>
          {part === null ? (
            <span className={styles["muted"]}>{copy.export.noPart}</span>
          ) : (
            <Fact source="workspace.part" value={part} />
          )}
          {pinned === null ? (
            <span className={styles["muted"]}>{copy.export.noPin}</span>
          ) : (
            <Fact source="workspace.artifact_ref" value={pinned} mono>
              {formatRef(pinned)}
            </Fact>
          )}
        </div>
        <PanelNote>{copy.export.subjectNote}</PanelNote>
        <PanelNote>{copy.export.twoSteps}</PanelNote>

        {blockerReason === null ? null : (
          <PanelNote live="assertive" data-export-refusal={blocker ?? ""}>
            {blockerReason}
          </PanelNote>
        )}

        <div className={styles["formats"]} role="group" aria-label={copy.export.format}>
          {EXPORT_FORMATS.map((name) => (
            <Button
              key={name}
              variant="toggle"
              pressed={format === name}
              data-export-format={name}
              onClick={() => {
                setFormat(name);
                // A changed field is a different submission (§22.2), so nothing
                // the previous one produced may survive the change.
                reset();
              }}
            >
              {name}
            </Button>
          ))}
        </div>

        <div className={styles["actions"]}>
          <Button
            variant="primary"
            data-export-run=""
            data-export-key={idempotencyKey}
            {...(blockerReason !== null
              ? { disabled: true as const, reason: blockerReason }
              : state === "exporting"
                ? { disabled: true as const, reason: copy.export.running }
                : {
                    onClick: () => {
                      run(submission);
                    },
                  })}
          >
            {state === "exporting" ? copy.export.running : copy.export.run}
          </Button>
          <Button variant="quiet" data-chrome-open-inspector="export" onClick={onOpenInspector}>
            {copy.chrome.more}
          </Button>
        </div>

        {row === null
          ? null
          : row.outputs.map((output) => (
              <div className={styles["file"]} key={output.blob} data-export-file={output.blob}>
                <Fact source="exports[].outputs[].bytes" value={output.bytes} className={styles["muted"]}>
                  {formatBytes(output.bytes)}
                </Fact>
                <Button
                  variant="secondary"
                  icon="download"
                  data-export-download={output.blob}
                  data-export-filename={output.filename}
                  {...(state === "transferring"
                    ? { disabled: true as const, reason: copy.export.downloading }
                    : {
                        onClick: () => {
                          download(output);
                        },
                      })}
                >
                  {state === "transferring" ? copy.export.downloading : copy.export.download}
                </Button>
              </div>
            ))}

        {refusal === null ? null : (
          <PanelNote live="assertive" data-export-refusal={refusal}>
            {copy.export.refusals[refusal]}
          </PanelNote>
        )}
        {downloadRefusal === null ? null : (
          <PanelNote live="assertive" data-export-download-refusal={downloadRefusal}>
            {copy.export.refusals[downloadRefusal]}
          </PanelNote>
        )}
      </PanelBody>
    </Panel>
  );
}
