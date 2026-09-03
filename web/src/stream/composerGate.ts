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
// the textarea turned off for each. That is right for `agent_unavailable` —
// there is nowhere to send — and produced two dead ends. `run_in_flight` means
// *there is somewhere and it is busy*: the refusal's own copy says "wait for it
// to finish, or cancel it", and waiting is exactly when an operator writes the
// next message. `no_session` means *Send will open the appropriate session*
// (Ask about the selected part, else a project session) and then post — one
// gesture, so the box stays live. With the box off, Send off and Cancel
// reporting `unavailable`, those refusals had no transition out of them at all.
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
 * Written as a set rather than as a pair of `===` checks because the interesting
 * property is the PARTITION of §7A.10's closed vocabulary: every reason is
 * either "nowhere to send" (`agent_unavailable`) or "the box stays live"
 * (`run_in_flight`, `no_session`), and a fourth reason added later has to land
 * on one side of it.
 */
export const COMPOSABLE_REASONS: readonly DisabledReason[] = ["run_in_flight", "no_session"];

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
  if (input.disabledReason === "agent_unavailable" || input.disabledReason === "run_in_flight") {
    return false;
  }
  if (input.sending) return false;
  return input.text.trim() !== "";
}

// -- the C8/C9 exception gate (§4.7, §23.8; AMENDED 2026-09-02 §0.2c) -------
//
// "Exactly one `data-variant="primary"` per shell, and in the steady state it
// is `[data-composer-send]`." The sole exception keys off the composer's OWN
// current `data-disabled-reason="agent_unavailable"` — never off last-observed
// provider health, which the review fix struck: health is *last observed*,
// never *current*, so a health predicate could hold while the composer is
// enabled and mint two primaries. The composer is the only surface that knows
// its current reason, and the ProvidersPanel is the other surface that must
// read it, so the reason is published here — one store, one writer (the
// mounted composer), read by both.

let gateReason: DisabledReason | null = null;
const gateListeners = new Set<() => void>();

/**
 * The composer's current `data-disabled-reason`, published by the mounted
 * `Composer` on every change and reset to `null` on unmount — an unmounted
 * composer has no current reason, so no exception can key off it.
 */
export const composerGateStore = {
  publish(reason: DisabledReason | null): void {
    if (reason === gateReason) return;
    gateReason = reason;
    for (const listener of gateListeners) listener();
  },
  subscribe(listener: () => void): () => void {
    gateListeners.add(listener);
    return () => {
      gateListeners.delete(listener);
    };
  },
  getSnapshot(): DisabledReason | null {
    return gateReason;
  },
};

/**
 * C8/C9's one predicate, spelled once. While it is `true` the provider
 * Sign-in action takes `primary` and the still-mounted Send demotes to
 * `secondary`; in every other state — including every credential
 * `rejected`/`expired`, which never disables the composer (§23.10) — Send is
 * the one primary and Sign-in renders `secondary` with the health axis
 * carrying the bad news.
 */
export function signInPrimary(reason: DisabledReason | null): boolean {
  return reason === "agent_unavailable";
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
