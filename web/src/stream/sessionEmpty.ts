// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Empty-session copy for the STREAM column (INTERFACE.md §7A.2).
//
// §7A.2's blank-canvas sentence names `create_part` because that is how the
// first part comes to exist from the browser. It is true only when the project
// has no parts. Reusing it whenever `GET /sessions` is empty — including when
// three parts exist and one is selected — is a lie: the context chips already
// name `part shelf` and the create affordance already offers "Ask about shelf".

import { copy } from "../copy";

/** Why the STREAM empty state is showing. Closed, so a test can address it. */
export const SESSION_EMPTY_KINDS = ["no_part", "no_session"] as const;
export type SessionEmptyKind = (typeof SESSION_EMPTY_KINDS)[number];

/**
 * `partCount` is `undefined` while `GET /parts` is in flight. A selected part
 * is enough to refuse the blank-canvas sentence; an empty list is the only
 * path that may claim there is no part yet.
 */
export function sessionEmptyKind(partCount: number | undefined): SessionEmptyKind {
  return partCount === 0 ? "no_part" : "no_session";
}

export function sessionEmptyBody(
  partCount: number | undefined,
  selectedPart: string | null,
): string {
  if (partCount === 0) return copy.composer.blankCanvas;
  if (selectedPart !== null) return copy.composer.noSessionSelectedPart(selectedPart);
  if (partCount === undefined) return copy.stream.noSessions;
  return copy.composer.noSessionHasParts;
}
