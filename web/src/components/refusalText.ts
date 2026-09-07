// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The one sentence a named refusal is rendered as (INTERFACE.md §2.4, §4.7,
// §23.14 item 15).
//
// It used to live inside `SignInDialog.tsx`, which is why the composer could not
// reach it and the providers panel imported it from a dialog it does not open.
// It is now a module neither surface owns, because three surfaces render the
// same refusals: the sign-in dialog, the providers panel, and the composer's
// attach action — one route (`POST /providers/attach`) is rendered by two of
// them a few inches apart on the same screen.
//
// **THE RAW-MESSAGE FALLBACK IS GONE, AND THAT IS THE FIX** (J-web-stream-6,
// RC-5). The old fallback returned `error.message` for any reason absent from
// the map, reasoning that "the server named it, so the server's words stand".
// That is true of a sentence and false of a *composed* string: the server builds
// `agent_unavailable`'s message as `f"{cause}: {detail}"`, so the panel rendered
// `no_provider_config: no provider config at <path>` — a machine reason code, a
// colon and an engine detail — inside a `role="alert"`. §4.7 forbids a machine
// string on a reading surface, and one unmapped reason is all it takes.
//
// So the ladder is: the structured §7A.8 cause the refusal carries, then the
// reason map, then §2.4's generic title. The reason CODE is still rendered — as
// a `Chip` beside the sentence, never inside it — which is what keeps an
// unmapped reason diagnosable without printing engine prose at an operator.

import { WorkspaceError } from "../api/client";
import { attachCauseOf } from "../api/attach";
import { copy } from "../copy";

/**
 * The refusal sentence for a named reason.
 *
 * Consults the attach cause FIRST: `agent_unavailable` and `attach_failed` are
 * one reason each covering seven distinct conditions, so mapping them by reason
 * alone would make three different states read identically — which is the one
 * thing the operator needs distinguished (§7A.8).
 */
export function refusalText(error: unknown): string {
  if (!(error instanceof WorkspaceError)) return copy.errors.title;
  const cause = attachCauseOf(error);
  if (cause !== null) return copy.attach.cause[cause];
  const known = copy.providers.refusal as Readonly<Record<string, string>>;
  return known[error.reason] ?? copy.errors.title;
}

/**
 * The machine reason a refusal carries, for the `Chip` beside the sentence.
 *
 * `null` for anything that is not a §2.4 envelope: a chip minted from a network
 * error would name a code no server ever sent.
 */
export function refusalCode(error: unknown): string | null {
  return error instanceof WorkspaceError ? error.reason : null;
}
