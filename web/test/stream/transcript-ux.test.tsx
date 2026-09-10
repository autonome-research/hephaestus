// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Transcript } from "../../src/components/stream/Transcript";
import { copy } from "../../src/copy";
import type { CurrentTurn } from "../../src/stream/conversation";
import { groupRows, historicalItem, liveItem, panelRows, type PanelRow } from "../../src/stream/transcript";

const working: CurrentTurn = { status: "Working", reason: null, runId: "run-current",
  terminalRunId: null, canSend: false, canAnswer: true, stopRequested: false };
function render(rows: readonly PanelRow[], currentTurn = working): Document {
  return new DOMParser().parseFromString(renderToStaticMarkup(
    <Transcript rows={rows} currentTurn={currentTurn} />), "text/html");
}
/** Resting text, excluding disclosure bodies (jsdom does not compute visibility). */
function face(node: Element): string {
  const clone = node.cloneNode(true) as Element;
  for (const details of clone.querySelectorAll("details:not([open])")) {
    for (const child of [...details.children]) if (child.tagName !== "SUMMARY") child.remove();
  }
  return clone.textContent ?? "";
}

describe("conversation-first transcript", () => {
  it("keeps history and incoming conversation continuous, with optional source detail", () => {
    const before = historicalItem({ run_id: "session", seq: 0, kind: "text_delta", payload: { text: "Same words." } }, "session");
    const after = liveItem({ run_id: "run-current", session_id: "session", seq: 0,
      kind: "text_delta", payload: { text: "Same words." } });
    const doc = render(panelRows([before], [{ entry: "event", item: after }]));
    expect(face(doc.body)).not.toMatch(/\b(recorded|live|operator|unrecorded)\b/i);
    expect(doc.querySelector('[data-seam] details')?.hasAttribute("open")).toBe(false);
    expect(doc.querySelectorAll("[data-row='text']")).toHaveLength(2);
    expect(doc.querySelector(`[data-event-id="${before.eventId}"]`)).not.toBeNull();
    expect(doc.querySelector(`[data-event-id="${after.eventId}"]`)).not.toBeNull();
  });

  it("keeps missing output and uncertain delivery visible without claiming a stopped run", () => {
    const doc = render([
      { row: "seam", key: "seam", kind: "mid-run" },
      { row: "local-prompt", key: "echo", text: "Please continue", state: "unknown" },
      { row: "resync", key: "gap", resync: { key: "gap", outcome: "gap", after: { run_id: "run-current", seq: 3 } } },
    ]);
    expect(face(doc.body)).toContain(copy.stream.seamMidRun);
    expect(face(doc.body)).toContain(copy.stream.localEcho.unknown);
    expect(face(doc.body)).toContain(copy.stream.resync.gap);
    expect(face(doc.body)).not.toMatch(/Stopped|Finished/);
  });

  it("does not echo rejected user text as a conversation turn", () => {
    const doc = render([{ row: "local-prompt", key: "rejected", text: "Retained draft", state: "refused", refusedReason: "run_in_flight" }]);
    expect(doc.body.textContent).not.toContain("Retained draft");
    expect(doc.querySelector("[data-markdown]")).toBeNull();
    expect(face(doc.body)).toContain(copy.stream.localEcho.refused.accessible);
    expect(face(doc.body)).toContain("run_in_flight");
  });

  it("scopes historical interruption to its earlier turn and does not announce current Stop", () => {
    const terminal = liveItem({ run_id: "run-old", session_id: "session", seq: 99,
      kind: "terminal", payload: { state: "cancelled", terminal_id: "terminal-old", payload: { reason: "user_cancel" } } });
    const doc = render([
      ...panelRows([], [], [{ turn: 0, seq: 0, text: "Earlier request", outcome: { state: "interrupted" } }], "session"),
      ...groupRows([terminal]),
    ]);
    const earlier = doc.querySelector('[data-row="turn-outcome"]')!;
    expect(earlier.previousElementSibling?.getAttribute("data-row")).toBe("user-prompt");
    expect(earlier.previousElementSibling?.textContent).toContain("Earlier request");
    expect(earlier.getAttribute("data-outcome-state")).toBe("interrupted");
    expect(face(earlier)).toContain("Interrupted");
    expect(face(earlier)).toContain(copy.composer.recoveryNext);
    expect(doc.querySelector('[data-terminal-state="cancelled"]')?.getAttribute("data-event-id")).toBe(terminal.eventId);
    expect(face(doc.body)).not.toContain("Stopped");
    expect(doc.querySelector("[role='status'], [aria-live]")).toBeNull();
    expect(doc.querySelector("[data-terminal-state] pre")?.textContent).toContain("user_cancel");
    expect(working.status).toBe("Working");
  });

  it("does not invent an outcome for an open historical prompt", () => {
    const rows = panelRows([], [], [{ turn: 0, seq: 0, text: "Open question" }], "session");
    const doc = render(rows);
    expect(doc.querySelector("[data-outcome-state]")).toBeNull();
    expect(face(doc.body)).not.toMatch(/finished|stopped|completed/i);
  });

  it("keeps an authoritative current question actionable and outside technical disclosures", () => {
    const question = liveItem({ run_id: "run-current", session_id: "session", seq: 0,
      kind: "question", payload: { question_id: "q-current", question: "Which edge?", options: ["Top", "Bottom"] } });
    // The shared task projection names the actionable address; active-run
    // ownership alone must no longer light up a stale question's controls.
    const doc = render(groupRows([question]), { ...working, status: "Waiting for your answer", questionId: "q-current" });
    const ask = doc.querySelector("[data-question-id='q-current']");
    expect(ask).not.toBeNull();
    expect(ask?.closest("details")).toBeNull();
    expect(face(doc.body)).toContain("Which edge?");
    expect(ask?.querySelector('[data-ask-option="Top"]')?.getAttribute("aria-disabled")).not.toBe("true");
    const unaddressed = render(groupRows([question]), working);
    expect(unaddressed.querySelector('[data-ask-option="Top"]')?.getAttribute("aria-disabled")).toBe("true");
    const blocked = render(groupRows([question]), { ...working, status: "Checking", canAnswer: false });
    expect(blocked.querySelector('[data-ask-option="Top"]')?.getAttribute("aria-disabled")).toBe("true");
  });
});
