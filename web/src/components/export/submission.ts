// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The one export state machine (INTERFACE.md §22.2, §22.7).
//
// Two components drive `POST /parts/{part}/export`: the Inspector's Export tab
// and the header chrome's compact dialog. They hold the IDENTICAL five pieces of
// state and run the IDENTICAL two transitions, and differ only in the submission
// they build and the markup they render — which is the part that legitimately
// differs. Before this module they shared their three pure helpers by import and
// their state machine by copy, and the copy diverged (J-web-stream-11):
//
// * the chrome's `run` cleared the result and the download refusal before
//   issuing; the panel's cleared neither. So in the panel a refused submission
//   after a successful one left the previous run's kerf block on screen under a
//   live alert — a `<Fact>` attributing a rendered value to a submission that
//   produced no kerf at all, which is a §1/§4.6 violation and not a cosmetic
//   one;
// * `refusalKey` was declared without an export, so the chrome inlined its body
//   twice, byte for byte, giving one mapping three copies.
//
// Whoever fixed the staleness fixed it in the chrome and could not carry it
// back, because nothing linked the two. A hook makes the divergence
// unrepresentable.
//
// **THE ONE REAL HAZARD, moved verbatim with its comment:** `SUBMISSION_KEYS` is
// module-scoped ON PURPOSE. Moving it into hook state would look like a passing
// refactor and would silently break §22.2's at-most-once guarantee, because a
// tab remount would mint a new key for a submission the operator has already
// sent.

import { useCallback, useState } from "react";
import {
  submissionKey,
  type DocKind,
  type DrawingKind,
  type DrawingSheet,
  type ExportFormat,
  type ExportLayout,
  type ExportOutput,
  type ExportResult,
  type ExportState,
  type ExportSubject,
} from "../../api/exports";
import { WorkspaceError } from "../../api/client";
import { copy } from "../../copy";

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

/** The refusal vocabulary both surfaces render, by name. */
export type ExportRefusal = keyof typeof copy.export.refusals;

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
  /**
   * The route path parameter, and the tool argument `name`. A held pin can
   * outlive a rail click (#100): hold jig, select kerf_card, export STEP —
   * that is a different submission than the jig's, and a key that omits the
   * part is `key_payload_mismatch` for the life of the page.
   */
  readonly part: string | null;
}

/**
 * The signature §22.2 keys on: a fresh key the moment any field changes, and the
 * same key for every retry of one unchanged submission.
 *
 * The artifact ref is in the signature because it is a field of the request —
 * exporting the same format from a different pin is a different submission, and
 * reusing the key across the two would be `key_payload_mismatch` by the server's
 * own reckoning. The part is in it for the same reason: it is the route's path
 * parameter and it lands in the tool arguments as `name` (#100).
 */
export function signature(submission: Submission): string {
  const parts: readonly string[] =
    submission.subject === "export"
      ? [submission.format, submission.layout, submission.blankWidth, submission.blankHeight]
      : submission.subject === "drawing"
        ? [submission.drawingKind, submission.sheet]
        : [submission.docKind];
  return [submission.subject, submission.part ?? "", submission.artifactRef ?? "", ...parts].join(
    "|",
  );
}

/** The kind segment of an artifact ref — the only thing the panel reads off one. */
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

/**
 * The sentence for a blocker, or `null` when nothing blocks.
 *
 * Was written out as an identical four-branch ternary in both components; the
 * chrome's copy is what a reviewer would have had to diff character by character
 * to know the two agreed.
 */
export function blockerReasonText(blocker: ExportBlocker | null): string | null {
  if (blocker === "no_part") return copy.export.noPart;
  if (blocker === "no_pin") return copy.export.noPin;
  if (blocker === "invalid_source") return copy.export.refusals.invalid_source;
  return null;
}

/** A named refusal reason, or `run_failed` for anything without one. */
export function refusalKey(error: unknown): ExportRefusal {
  const reason = error instanceof WorkspaceError ? error.reason : "";
  return reason in copy.export.refusals ? (reason as ExportRefusal) : "run_failed";
}

/**
 * The key for one submission, stable across retries of that submission.
 *
 * Module-scoped rather than component state so a remount — switching Inspector
 * tabs, which unmounts the panel — does not re-mint a key for a submission the
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

/** What a component gets back: the five values it renders and the three acts. */
export interface ExportSubmissionRun {
  readonly state: ExportState;
  readonly result: ExportResult | null;
  readonly refusal: ExportRefusal | null;
  readonly downloadRefusal: ExportRefusal | null;
  /** Issue one submission. Clears everything the PREVIOUS one produced. */
  readonly run: (submission: Submission) => void;
  /** Fetch one produced file's bytes (§22.4's second step). */
  readonly download: (output: ExportOutput) => void;
  /** Forget the previous submission without issuing one — a changed field. */
  readonly reset: () => void;
}

/**
 * The state machine both export surfaces run.
 *
 * `run` clears the refusal, the download refusal AND the result before issuing,
 * which is the correct semantics for a NEW submission and the half the chrome
 * already had: §22.2 (tightened 2026-09-05) — a new submission clears the
 * previous one's result and download refusal, and no fact may survive into a
 * submission other than the one that produced it.
 */
export function useExportSubmission(
  onExport: (submission: Submission) => Promise<ExportResult>,
  onDownload: (output: ExportOutput) => Promise<void>,
): ExportSubmissionRun {
  const [state, setState] = useState<ExportState>("idle");
  const [result, setResult] = useState<ExportResult | null>(null);
  const [refusal, setRefusal] = useState<ExportRefusal | null>(null);
  const [downloadRefusal, setDownloadRefusal] = useState<ExportRefusal | null>(null);

  const reset = useCallback((): void => {
    setResult(null);
    setRefusal(null);
    setDownloadRefusal(null);
  }, []);

  const run = useCallback(
    (submission: Submission): void => {
      setState("exporting");
      setRefusal(null);
      setDownloadRefusal(null);
      setResult(null);
      void onExport(submission)
        .then((document) => {
          setResult(document);
          setState("idle");
        })
        .catch((error: unknown) => {
          setRefusal(refusalKey(error));
          setState("refused");
        });
    },
    [onExport],
  );

  const download = useCallback(
    (output: ExportOutput): void => {
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

  return { state, result, refusal, downloadRefusal, run, download, reset };
}
