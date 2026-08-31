// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Timeline marks from `GET /parts/{part}/build` (INTERFACE.md §0.1).
//
// After the engine persisted worker per-statement `checkpoints` on the §8
// record, this helper projects those stops and the positions the error
// object already named (last-good / failed / current). A mark invented
// from the script's statements, or from a recount of `geometries`, would
// be a client-side timeline the engine did not project.

import type { BuildDocument, StatementCheckpoint } from "../../api/types";

/** Closed. `statement` is a projected executor checkpoint. */
export const TIMELINE_KINDS = ["statement", "last_good", "failed", "current"] as const;
export type TimelineKind = (typeof TIMELINE_KINDS)[number];

export interface TimelineMark {
  readonly kind: TimelineKind;
  /** The artifact this mark rewinds to, or `null` when the engine named none. */
  readonly artifact_ref: string | null;
  readonly index?: number;
  readonly line?: number;
  readonly statement?: string;
  readonly bound?: readonly string[];
  readonly shapes?: readonly string[];
}

function rewindable(mark: TimelineMark): boolean {
  return mark.kind === "last_good" || mark.kind === "failed" || mark.kind === "current";
}

/** The stops the scrubber may pin: last-good / failed / current only. */
export function rewindMarks(marks: readonly TimelineMark[]): readonly TimelineMark[] {
  return marks.filter(rewindable);
}

function markFromCheckpoint(
  checkpoint: StatementCheckpoint,
  lastGood: string | null,
): TimelineMark {
  const ref = checkpoint.artifact_ref;
  const kind = lastGood !== null && ref === lastGood ? "last_good" : "statement";
  return {
    kind,
    artifact_ref: ref,
    index: checkpoint.index,
    line: checkpoint.line,
    statement: checkpoint.statement,
    bound: checkpoint.bound,
    shapes: checkpoint.shapes,
  };
}

/**
 * The Timeline's stops, in order: every projected checkpoint, then the
 * failed statement or the current artifact. A checkpoint whose
 * `artifact_ref` is the error's last-good ref is the last-good stop —
 * the engine named that join, not the client.
 *
 * `not_built` has no marks: silence is a named absence in the panel, not an
 * empty scrubber that looks like "rewound to the start".
 */
export function marksFromBuild(build: BuildDocument): readonly TimelineMark[] {
  if (build.status === "not_built") return [];
  const marks: TimelineMark[] = [];
  const lastGood = build.error?.last_good_artifact_ref ?? null;
  for (const checkpoint of build.checkpoints ?? []) {
    marks.push(markFromCheckpoint(checkpoint, lastGood));
  }
  if (lastGood !== null && !marks.some((mark) => mark.kind === "last_good")) {
    marks.push({ kind: "last_good", artifact_ref: lastGood });
  }
  if (build.status === "error") {
    marks.push({ kind: "failed", artifact_ref: build.artifact_ref ?? null });
  } else if (build.status === "ok") {
    marks.push({ kind: "current", artifact_ref: build.artifact_ref ?? null });
  }
  return marks;
}

/**
 * Which rewindable mark the pin is on.
 *
 * Holding the last-good ref selects that mark. Any other pin — including
 * `null` after a failed build with no current artifact — selects the
 * failed/current mark the engine named. This is pin-matching, not a
 * measurement.
 */
export function kindForPin(
  marks: readonly TimelineMark[],
  pin: string | null,
): TimelineKind | null {
  const rewindableMarks = rewindMarks(marks);
  if (rewindableMarks.length === 0) return null;
  const lastGood = rewindableMarks.find((mark) => mark.kind === "last_good");
  if (lastGood !== undefined && pin !== null && pin === lastGood.artifact_ref) {
    return "last_good";
  }
  const rest = rewindableMarks.find((mark) => mark.kind !== "last_good");
  return rest?.kind ?? lastGood?.kind ?? null;
}

/** The index the scrubber sits on for a pin. `0` when there is nothing to match. */
export function indexForPin(marks: readonly TimelineMark[], pin: string | null): number {
  const rewindableMarks = rewindMarks(marks);
  const kind = kindForPin(marks, pin);
  if (kind === null) return 0;
  const index = rewindableMarks.findIndex((mark) => mark.kind === kind);
  return index === -1 ? 0 : index;
}

export type TimelineAction =
  | { readonly action: "hold"; readonly ref: string }
  | { readonly action: "follow"; readonly currentRef: string | null };

/**
 * What a scrubber index does to the pin.
 *
 * Last-good with a ref is `hold` — rewind. Every other rewindable mark
 * follows current, including a failed build whose `artifact_ref` is null.
 * The index is over `rewindMarks`, not the full projected list.
 */
export function actionForIndex(
  marks: readonly TimelineMark[],
  index: number,
  currentRef: string | null,
): TimelineAction | null {
  const mark = rewindMarks(marks)[index];
  if (mark === undefined) return null;
  if (mark.kind === "last_good" && mark.artifact_ref !== null) {
    return { action: "hold", ref: mark.artifact_ref };
  }
  return { action: "follow", currentRef };
}
