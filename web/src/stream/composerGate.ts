// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Two composer decisions that are not layout (INTERFACE.md §7A.5, §7A.10).
//
// They live beside the component rather than in it for the reason the transcript
// model does: a claim about when the operator can type, and a claim about which
// keystroke sends a turn, are both testable without a browser, and a claim
// tested only through rendered markup is a claim that can only be tested in the
// states a parent can drive it into from props.
//
// **1. `disabled` is not one state.** §7A.10's `data-disabled-reason` vocabulary
// is closed at three, and the shipped composer treated all three identically:
// the textarea turned off for each. That is right for two of them and produced a
// dead end for the third. `agent_unavailable` and `no_session` mean *there is
// nowhere to send this*, so a live text box would be collecting words for no
// recipient. `run_in_flight` means *there is somewhere and it is busy* — the
// refusal's own copy says "wait for it to finish, or cancel it", and waiting is
// exactly when an operator writes the next message. With the box disabled, Send
// disabled and Cancel reporting `unavailable`, that refusal had no transition out
// of it at all short of switching session tabs.
//
// **2. Enter sends.** §7A says nothing about keys, which is why the shipped
// composer had none: every turn cost a trip from the keyboard to the pointer,
// which is the difference between a chat and a form. Shift+Enter keeps the
// newline, and a composition in progress keeps Enter — an IME candidate window
// treats it as "commit this candidate", and sending there sends half a word.

import type { DisabledReason } from "../components/stream/Composer";

/**
 * The `data-disabled-reason` values that still admit typing.
 *
 * A one-member set today, and it is written as a set rather than as `reason ===
 * "run_in_flight"` because the interesting property is the PARTITION of §7A.10's
 * closed vocabulary: every reason is either "nowhere to send" or "somewhere,
 * busy", and a fourth reason added later has to be put on one side of it.
 */
export const COMPOSABLE_REASONS: readonly DisabledReason[] = ["run_in_flight"];

/** May the operator type? `null` is enabled; see `COMPOSABLE_REASONS`. */
export function isComposable(reason: DisabledReason | null): boolean {
  return reason === null || COMPOSABLE_REASONS.includes(reason);
}

/** The parts of a keydown this decision reads. Structural, so a test needs no DOM. */
export interface SendKey {
  readonly key: string;
  readonly shiftKey: boolean;
  readonly isComposing: boolean;
}

/** Does this keystroke mean "send the turn"? */
export function isSendKey(event: SendKey): boolean {
  if (event.key !== "Enter") return false;
  if (event.shiftKey) return false;
  return !event.isComposing;
}

/**
 * May this control start a turn? Enter, the Send button, and `submit()` share
 * this predicate — a gate that lived only on the button would be one the
 * keyboard walks past, and a gate that lived only in `submit` would leave
 * Send looking enabled while a click did nothing (#44).
 */
export function canSendTurn(input: {
  readonly disabledReason: DisabledReason | null;
  readonly text: string;
  readonly sending: boolean;
}): boolean {
  if (input.disabledReason !== null) return false;
  if (input.sending) return false;
  return input.text.trim() !== "";
}

/** Closed reasons Cancel names when it is not available (§7A.5, §7A.6). */
export const CANCEL_REASONS = ["cancelIdle", "cancelNoRun", "cancelNoStream"] as const;
export type CancelReason = (typeof CANCEL_REASONS)[number];

/**
 * Cancel is available iff the live run id is known and the socket is `live`.
 *
 * `runId` means the run that is live *now* — not the last one this tab saw.
 * Between submit and the first matching frame the id is unknown (`cancelNoRun`);
 * a socket that is not `live` cannot learn one (`cancelNoStream`); idle Cancel
 * stays rendered and names `cancelIdle` (§7A.6). `awaitingRun` is the submit
 * window, not a second enablement gate — a live id on a live socket is enough.
 */
export function cancelAvailability(input: {
  readonly liveRunId: string | null;
  readonly streamLive: boolean;
  readonly awaitingRun: boolean;
}): { readonly available: true } | { readonly available: false; readonly reason: CancelReason } {
  if (input.liveRunId !== null && input.streamLive) return { available: true };
  if (!input.streamLive) return { available: false, reason: "cancelNoStream" };
  if (input.awaitingRun) return { available: false, reason: "cancelNoRun" };
  return { available: false, reason: "cancelIdle" };
}
