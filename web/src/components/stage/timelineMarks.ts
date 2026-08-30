// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Timeline marks from `GET /parts/{part}/build` (INTERFACE.md §0.1).
//
// The incremental executor records per-statement checkpoints **inside the
// worker**. Those checkpoints are not a field on the HTTP BuildResult
// projection. What the projection *does* carry, when a build failed, is
// `error.built_through`, `error.last_good`, and `error.last_good_artifact_ref`.
// This module emits only those positions. A mark invented from the script's
// statements, or from a recount of `geometries`, would be a client-side
// timeline the engine did not project.

import type { BuildDocument } from "../../api/types";

/** The three positions the build projection can name. Closed. */
export const TIMELINE_KINDS = ["last_good", "failed", "current"] as const;
export type TimelineKind = (typeof TIMELINE_KINDS)[number];

export interface TimelineMark {
  readonly kind: TimelineKind;
  /** The artifact this mark rewinds to, or `null` when the engine named none. */
  readonly artifact_ref: string | null;
}

/**
 * The scrubber's stops, in order: last-good (if the error named a checkpoint),
 * then the failed statement, or — on a successful build — the current artifact
 * alone.
 *
 * `not_built` has no marks: silence is a named absence in the panel, not an
 * empty scrubber that looks like "rewound to the start".
 */
export function marksFromBuild(build: BuildDocument): readonly TimelineMark[] {
  if (build.status === "not_built") return [];
  const marks: TimelineMark[] = [];
  const lastGood = build.error?.last_good_artifact_ref ?? null;
  if (lastGood !== null) {
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
 * Which mark the pin is on.
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
  if (marks.length === 0) return null;
  const lastGood = marks.find((mark) => mark.kind === "last_good");
  if (lastGood !== undefined && pin !== null && pin === lastGood.artifact_ref) {
    return "last_good";
  }
  const rest = marks.find((mark) => mark.kind !== "last_good");
  return rest?.kind ?? lastGood?.kind ?? null;
}

/** The index the scrubber sits on for a pin. `0` when there is nothing to match. */
export function indexForPin(marks: readonly TimelineMark[], pin: string | null): number {
  const kind = kindForPin(marks, pin);
  if (kind === null) return 0;
  const index = marks.findIndex((mark) => mark.kind === kind);
  return index === -1 ? 0 : index;
}

export type TimelineAction =
  | { readonly action: "hold"; readonly ref: string }
  | { readonly action: "follow"; readonly currentRef: string | null };

/**
 * What a scrubber index does to the pin.
 *
 * Last-good with a ref is `hold` — rewind. Every other mark follows current,
 * including a failed build whose `artifact_ref` is null.
 */
export function actionForIndex(
  marks: readonly TimelineMark[],
  index: number,
  currentRef: string | null,
): TimelineAction | null {
  const mark = marks[index];
  if (mark === undefined) return null;
  if (mark.kind === "last_good" && mark.artifact_ref !== null) {
    return { action: "hold", ref: mark.artifact_ref };
  }
  return { action: "follow", currentRef };
}
