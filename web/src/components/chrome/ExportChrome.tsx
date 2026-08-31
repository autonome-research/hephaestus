// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Compact export control for header chrome. Bound to the workspace pin
// (INTERFACE.md §22.5): the request carries `WorkspaceState.artifact_ref`
// verbatim. Formats, blockers, and the submission key are the same ones the
// inspector tab uses — this is not a second exporter.
//
// Drawings, documents, nested-sheet blanks, kerf readout, and history stay
// on the inspector Export tab. Chrome is the simple "take this geometry out"
// path: six formats, as-built, Export.

import { useState } from "react";
import { EXPORT_FORMATS, type ExportFormat, type ExportState } from "../../api/exports";
import { WorkspaceError } from "../../api/client";
import { copy } from "../../copy";
import { Button, Panel, PanelBody, PanelHeader, PanelNote, formatRef } from "../../system";
import { Fact } from "../Fact";
import {
  exportBlocker,
  submissionKeyFor,
  type Submission,
} from "../inspector/ExportPanel";
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
  readonly onExport: (submission: Submission) => Promise<unknown>;
  readonly onOpenInspector: () => void;
}

export function ExportChrome(props: ExportChromeProps): React.JSX.Element {
  const { part, pinned, pinMode, onExport, onOpenInspector } = props;
  const [format, setFormat] = useState<ExportFormat>("step");
  const [state, setState] = useState<ExportState>("idle");
  const [refusal, setRefusal] = useState<keyof typeof copy.export.refusals | null>(null);

  const submission: Submission = { ...CHROME_SUBMISSION, format, artifactRef: pinned };
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

  const run = (): void => {
    setState("exporting");
    setRefusal(null);
    void onExport(submission)
      .then(() => {
        setState("idle");
      })
      .catch((error: unknown) => {
        const reason = error instanceof WorkspaceError ? error.reason : "";
        setRefusal(
          reason in copy.export.refusals
            ? (reason as keyof typeof copy.export.refusals)
            : "run_failed",
        );
        setState("refused");
      });
  };

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

        {blockerReason === null ? null : (
          <PanelNote data-export-refusal={blocker ?? ""}>{blockerReason}</PanelNote>
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
              }}
            >
              {name}
            </Button>
          ))}
        </div>

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
          <Button variant="quiet" data-chrome-open-inspector="export" onClick={onOpenInspector}>
            {copy.chrome.more}
          </Button>
        </div>

        {refusal === null ? null : (
          <PanelNote data-export-refusal={refusal}>{copy.export.refusals[refusal]}</PanelNote>
        )}
      </PanelBody>
    </Panel>
  );
}
