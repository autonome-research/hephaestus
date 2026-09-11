// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { DisclosureOwner, PersistentDetails, useDisclosure } from "../../stream/disclosure";

import { readAudit, readTerminal } from "../../api/events";
import { readableReason, sanitizeDiagnostic, outcomeLabel } from "../../stream/outcome";
import { copy } from "../../copy";
import { Markdown } from "../../stream/markdown";
import type { CurrentTurn } from "../../stream/conversation";
import type { RuntimeFault } from "../../stream/runtimeFault";
import type { PanelRow, TranscriptItem } from "../../stream/transcript";
import { presentationRows, runsWithTerminal } from "../../stream/transcript";
import { AskUserWidget } from "./AskUserWidget";
import { askContent } from "../../stream/ask";
import { TextBlock, ThoughtSection } from "./ThoughtSection";
import { EventImageInline } from "./EventImage";
import { ToolChip } from "./ToolChip";
import styles from "./Transcript.module.css";

export function Transcript({
  rows,
  sessionId = null,
  runtimeFault = null,
  currentTurn,
}: {
  readonly rows: readonly PanelRow[];
  readonly sessionId?: string | null;
  readonly currentTurn?: CurrentTurn;
  readonly runtimeFault?: RuntimeFault | null;
}): React.JSX.Element {
  const terminals = runsWithTerminal(rows);
  return (
    <ol className={styles["transcript"]} data-testid="transcript">
      {presentationRows(rows).map((row) => (
        <li
          key={row.key}
          className={styles["row"]}
          data-row={row.row}
          data-row-key={row.key}
          {...(row.row === "local-prompt"
            ? {
                "data-local-echo": "1",
                "data-echo-state": row.state ?? "sent",
                ...(typeof row.refusedReason === "string"
                  ? { "data-refused-reason": row.refusedReason }
                  : {}),
              }
            : {})}
          {...(row.row === "user-prompt" ? { "data-event-id": row.eventId } : {})}
          {...(row.row === "turn-outcome"
            ? { "data-outcome-state": row.outcome.state }
            : {})}
          {...(row.row === "run-start" ? { "data-run-id": row.runId } : {})}
        >
          <DisclosureOwner.Provider value={sessionId === null ? null : JSON.stringify([sessionId, row.key])}>
            <Row row={row} runtimeFault={runtimeFault} terminals={terminals} currentTurn={currentTurn} />
          </DisclosureOwner.Provider>
        </li>
      ))}
    </ol>
  );
}

function Row({ row, runtimeFault, terminals, currentTurn }: {
  readonly currentTurn?: CurrentTurn | undefined;
  readonly row: PanelRow;
  readonly runtimeFault: RuntimeFault | null;
  readonly terminals: ReadonlySet<string>;
}): React.JSX.Element | null {
  switch (row.row) {
    case "text":
      return <TextBlock items={row.items} />;
    case "thought":
      return <ThoughtSection items={row.items} />;
    case "chip":
      return <ToolChip toolName={row.toolName} call={row.call} result={row.result}
        images={row.images} status={row.status} />;
    case "cycle":
      // Unfolded before reconciliation by presentationRows.
      return null;
    case "ask": {
      const runId = row.recovery?.run_id ?? (row.question ?? row.call ?? row.answer)?.runId ?? null;
      return (
        <AskUserWidget
          row={row}
          taskStatus={currentTurn?.status === "Checking" ? copy.composer.checking : currentTurn?.status ?? null}
          executionAllowed={currentTurn === undefined || (currentTurn.canAnswer && currentTurn.runId === runId
            && currentTurn.questionId != null && currentTurn.questionId === askContent(row).questionId)}
          death={{
            fault: runtimeFault,
            runHasTerminal: runId !== null && (terminals.has(runId) || currentTurn?.terminalRunId === runId),
          }}
        />
      );
    }
    case "image":
      return <EventImageInline item={row.item} />;
    case "audit":
      return (
        <PersistentDetails className={styles["provenance"]} data-event-id={row.item.eventId}
          data-surface={row.item.surface} data-audit="1">
          <summary>{copy.stream.audit}</summary>
          <p className={styles["note"]}>{readAudit(row.item.payload) ?? copy.absent.unavailable}</p>
        </PersistentDetails>
      );
    case "terminal":
      return <TerminalBand item={row.item} currentTurn={currentTurn} />;
    case "unknown":
      return (
        <PersistentDetails className={styles["provenance"]} data-event-id={row.item.eventId}
          data-surface={row.item.surface} data-unknown-kind={row.item.rawKind}>
          <summary>{copy.stream.unknownKind}</summary>
          <pre className={styles["raw"]}>{JSON.stringify(row.item.payload, null, 2)}</pre>
        </PersistentDetails>
      );
    case "absence":
      return <p className={styles["absence"]} data-absence={row.absence}
        title={copy.stream.absenceDetail[row.absence]}>{copy.stream.absence[row.absence]}</p>;
    case "seam":
      // Source differences are inspectable, not a second conversation boundary.
      // A known missing prefix remains visible without opening the disclosure.
      return (
        <div data-seam="1" data-seam-kind={row.kind}>
          {row.kind === "mid-run" ? <p className={styles["absence"]}>{copy.stream.seamMidRun}</p> : null}
          <PersistentDetails className={styles["provenance"]}>
            <summary>{copy.stream.deliveryDetails}</summary>
            <p className={styles["note"]}>{copy.stream.seam}</p>
          </PersistentDetails>
        </div>
      );
    case "local-prompt":
      // A refused attempt is not a user turn. Keep its reason, not a second
      // copy of the draft the controller retained in the composer.
      if (row.state === "refused") {
        return <p className={styles["absence"]} data-send-rejected="">
          {copy.stream.localEcho.refused.accessible}
          {row.refusedReason ? ` (${row.refusedReason})` : null}
        </p>;
      }
      return (
        <div className={styles["localPrompt"]}>
          <p className={styles["markerLine"]}>
            <span className={styles["roleMarker"]}>{copy.stream.userPrompt.marker}</span>
            {row.state === "unknown" ? <span className={styles["presentationMarker"]}>
              {copy.stream.localEcho.unknown}
            </span> : null}
          </p>
          <div className={styles["localPromptText"]} data-markdown="">
            <Markdown text={row.text} preserveLineBreaks />
          </div>
        </div>
      );
    case "user-prompt":
      return (
        <div className={styles["userPrompt"]}>
          <p className={styles["markerLine"]} data-prompt-origin={row.origin ?? "operator"}>
            <span className={styles["roleMarker"]}>
              {row.origin === "agent" ? copy.stream.userPrompt.markerAgent : copy.stream.userPrompt.marker}
            </span>
          </p>
          {row.textUnrecoverable ? (
            <p className={styles["promptTextAbsent"]} data-prompt-text="unrecoverable">
              {copy.stream.userPrompt.unrecoverable}
            </p>
          ) : (
            <div className={styles["localPromptText"]} data-markdown="">
              <Markdown text={row.text} preserveLineBreaks />
            </div>
          )}
          {row.envelope === null ? null : <PromptEnvelope envelope={row.envelope} />}
        </div>
      );
    case "turn-outcome": {
      const content = <>
        <span>{outcomeLabel(row.outcome.state)}</span>
        {row.outcome.message ? <span className={styles["turnOutcomeMessage"]}>{readableReason(row.outcome.message)}</span> : null}
      </>;
      return row.outcome.state === "completed" ? (
        <PersistentDetails className={styles["provenance"]}>
          <summary>{copy.stream.turnDetails}</summary>
          <p className={styles["note"]}>{content}</p>
        </PersistentDetails>
      ) : <div className={styles["turnOutcome"]}>{content}
        {row.outcome.state === "error" || row.outcome.state === "interrupted" ? <p>{copy.composer.recoveryNext}</p> : null}
        <PersistentDetails className={styles["provenance"]}><summary>{copy.stream.ask.details}</summary>
          <pre className={styles["raw"]}>{sanitizeDiagnostic(row.outcome)}</pre>
        </PersistentDetails>
      </div>;
    }
    case "run-start":
      return (
        <PersistentDetails className={styles["provenance"]}>
          <summary>{copy.stream.runDetails}</summary>
          <p className={styles["note"]}>{row.runId}</p>
        </PersistentDetails>
      );
    case "resync":
      return (
        <div className={styles["resync"]} data-resync={row.resync.outcome}
          title={copy.stream.resyncDetail[row.resync.outcome]}>
          <p className={styles["note"]}>{copy.stream.resync[row.resync.outcome]}</p>
          <PersistentDetails className={styles["provenance"]}>
            <summary>{copy.stream.deliveryDetails}</summary>
            <p className={styles["note"]}>{copy.stream.resyncDetail[row.resync.outcome]}</p>
            {row.resync.after === null ? null : <p className={styles["resyncAfter"]}>
              {copy.stream.resync.after}: {row.resync.after.run_id}#{row.resync.after.seq}
            </p>}
          </PersistentDetails>
        </div>
      );
  }
}

function PromptEnvelope({ envelope }: { readonly envelope: string }): React.JSX.Element {
  const [open, setOpen] = useDisclosure("envelope");
  return (
    <details className={styles["envelope"]} data-prompt-envelope="" aria-expanded={open}
      title={copy.stream.userPrompt.envelope.title}
      onToggle={(event) => { setOpen(event.currentTarget.open); }}>
      <summary className={styles["envelopeSummary"]}>{copy.stream.userPrompt.envelope.label}</summary>
      <pre className={styles["envelopeBody"]}>{envelope}</pre>
    </details>
  );
}

/** Event outcomes describe this run, never the current session's activity. */
function TerminalBand({ item, currentTurn }: {
  readonly item: TranscriptItem;
  readonly currentTurn?: CurrentTurn | undefined;
}): React.JSX.Element {
  const payload = readTerminal(item.payload);
  const state = payload?.state ?? null;
  const known = state === null ? copy.stream.terminal.unknown : outcomeLabel(state);
  return (
    <div className={styles["terminal"]} data-event-id={item.eventId} data-surface={item.surface}
      data-terminal-state={state ?? "unknown"}
      {...(payload?.terminalId == null ? {} : { "data-terminal-id": payload.terminalId })}
      {...(payload?.backpressure === true ? { "data-terminal-backpressure": "1" } : {})}
      {...(currentTurn?.terminalRunId === item.runId ? { role: "status", "aria-live": "polite" as const } : {})}
      title={payload?.terminalId == null ? copy.stream.terminal.title
        : `${copy.stream.terminal.title}. ${copy.stream.terminal.identity}: ${payload.terminalId}`}>
      <span>{known}</span>
      {state === "failed" || state === "interrupted" ? <>
        <p>{readableReason(item.payload)}</p><p>{copy.composer.recoveryNext}</p>
      </> : null}
      {payload?.backpressure === true ? <span className={styles["note"]}>{copy.stream.terminal.backpressure}</span> : null}
      <PersistentDetails className={styles["provenance"]}>
        <summary>{copy.stream.ask.details}</summary>
        <pre className={styles["raw"]}>{sanitizeDiagnostic(item.payload)}</pre>
      </PersistentDetails>
    </div>
  );
}
