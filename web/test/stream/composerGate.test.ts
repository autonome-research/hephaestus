// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The composer can be typed into, and Enter sends (INTERFACE.md §7A.5, §7A.10).
//
// TWO DEFECTS THESE ASSERTIONS PIN.
//
// **The dead end.** §7A.10's `data-disabled-reason` vocabulary is closed at
// three and the shipped composer disabled the textarea for all three alike. Two
// of them mean "there is nowhere to send this"; `run_in_flight` means "there is
// somewhere and it is busy", and its own refusal copy tells the operator to wait
// or cancel. With the box off, Send off, and Cancel reporting `unavailable`,
// there was no transition out of that refusal at all — the operator's only exit
// was another session tab.
//
// **No keyboard.** A textarea whose only send affordance is a button is a form.
// Every turn cost a trip to the pointer, which is most of what "the chat is not
// functional" meant.

import { describe, expect, it } from "vitest";
import { DISABLED_REASONS } from "../../src/components/stream/Composer";
import {
  CANCEL_REASONS,
  canSendTurn,
  cancelAvailability,
  COMPOSABLE_REASONS,
  isComposable,
  isSendKey,
} from "../../src/stream/composerGate";

describe("which disabled reasons still admit typing", () => {
  it("partitions §7A.10's closed vocabulary, leaving none unclassified", () => {
    // The property that matters is the PARTITION: a fourth reason added later
    // has to land on one side of it, and this assertion is what notices when
    // one does not.
    for (const reason of DISABLED_REASONS) {
      expect(typeof isComposable(reason), reason).toBe("boolean");
    }
    const composable = DISABLED_REASONS.filter((reason) => isComposable(reason));
    expect(composable).toEqual(COMPOSABLE_REASONS);
  });

  it("keeps the box live while a turn finishes, so the refusal has a way out", () => {
    expect(isComposable("run_in_flight")).toBe(true);
  });

  it("turns it off when there is genuinely nowhere to send", () => {
    expect(isComposable("no_session")).toBe(false);
    expect(isComposable("agent_unavailable")).toBe(false);
  });

  it("is enabled with no reason at all", () => {
    expect(isComposable(null)).toBe(true);
  });
});

describe("which keystroke sends a turn", () => {
  const key = (patch: Partial<Parameters<typeof isSendKey>[0]> = {}) =>
    isSendKey({ key: "Enter", shiftKey: false, isComposing: false, ...patch });

  it("sends on Enter", () => {
    expect(key()).toBe(true);
  });

  it("opens a line on Shift+Enter", () => {
    expect(key({ shiftKey: true })).toBe(false);
  });

  it("leaves Enter to an IME candidate window", () => {
    // Sending mid-composition sends half a word, and the operator loses the
    // rest of it — which is worse than no binding at all.
    expect(key({ isComposing: true })).toBe(false);
  });

  it("sends on nothing else", () => {
    for (const other of ["Tab", "Escape", "a", " ", "NumpadEnter"]) {
      expect(key({ key: other }), other).toBe(false);
    }
  });
});

describe("Send and Cancel share one predicate each", () => {
  it("lets Send start a turn only when there is a session, text, and no in-flight POST", () => {
    const ok = { disabledReason: null, text: "Add a 2 mm chamfer.", sending: false };
    expect(canSendTurn(ok)).toBe(true);
    expect(canSendTurn({ ...ok, text: "   " })).toBe(false);
    expect(canSendTurn({ ...ok, sending: true })).toBe(false);
    expect(canSendTurn({ ...ok, disabledReason: "no_session" })).toBe(false);
    expect(canSendTurn({ ...ok, disabledReason: "run_in_flight" })).toBe(false);
    expect(canSendTurn({ ...ok, disabledReason: "agent_unavailable" })).toBe(false);
  });

  it("offers Cancel iff the live run id is known and the socket is live", () => {
    expect(
      cancelAvailability({ liveRunId: "run-1", streamLive: true, awaitingRun: true }),
    ).toEqual({ available: true });
    // #45: a live id on a live socket is enough — not also `awaitingRun`.
    expect(
      cancelAvailability({ liveRunId: "run-1", streamLive: true, awaitingRun: false }),
    ).toEqual({ available: true });
    expect(
      cancelAvailability({ liveRunId: null, streamLive: true, awaitingRun: true }),
    ).toEqual({ available: false, reason: "cancelNoRun" });
    expect(
      cancelAvailability({ liveRunId: null, streamLive: true, awaitingRun: false }),
    ).toEqual({ available: false, reason: "cancelIdle" });
    expect(
      cancelAvailability({ liveRunId: "run-1", streamLive: false, awaitingRun: true }),
    ).toEqual({ available: false, reason: "cancelNoStream" });
    expect(CANCEL_REASONS).toEqual(["cancelIdle", "cancelNoRun", "cancelNoStream"]);
  });
});
