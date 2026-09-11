// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { expect, it } from "vitest";
import { createConversationStore, currentTurn } from "../../src/stream/conversation";
import { askContent, readableAnswer } from "../../src/stream/ask";
import { panelRows, historicalItem } from "../../src/stream/transcript";
import { readableReason, sanitizeDiagnostic } from "../../src/stream/outcome";
import { modelState } from "../fixtures/models";
import type { ExecutionSnapshot } from "../../src/api/sessions";
const idle: ExecutionSnapshot = { epoch: "e", version: 1, run_id: null, active_run_id: null, terminal: null, admission_available: true };
const active = { ...idle, version: 2, run_id: "run", active_run_id: "run", admission_available: false };
function fixture() {
  const s = createConversationStore();
  s.modelSnapshot("s", modelState, idle, s.ticket());
  s.draft("s", "immutable attempt");
  const attempt = s.begin("s", { part: "tread" })!;
  s.snapshot("s", active, s.ticket());
  s.frame({ session_id: "s", run_id: "run", seq: 1, kind: "question", payload: {
    question_id: "q", question: "Which stock?", options: ["Use 6 mm stock"], allow_free_text: false,
  } });
  const c = s.get("s");
  const row = panelRows(c.history.items, c.live.entries).find(r => r.row === "ask")!;
  if (row.row !== "ask") throw new Error("question missing");
  return { s, row, attempt };
}
it("retains the reviewed model revision actually sent, not a newer intervening model read", () => {
  const s = createConversationStore();
  s.modelSnapshot("s", { ...modelState, revision: { ...modelState.revision, version: modelState.revision.version + 1 } }, idle, s.ticket());
  s.draft("s", "reviewed request");
  expect(s.begin("s", undefined, modelState.revision)?.modelRevision).toEqual(modelState.revision);
});
it("projects waiting, recording, accepted Working even with the prompt POST unresolved", () => {
  const { s, row, attempt } = fixture();
  expect(currentTurn(s.get("s"))).toMatchObject({ status: "Waiting for your answer", questionId: "q", canSend: false });
  expect(s.beginAnswer("s", row)).toBe(true);
  expect(s.beginAnswer("s", row)).toBe(false);
  expect(currentTurn(s.get("s")).status).toBe("Recording answer");
  s.answer("s", "q", { phase: "settled", document: { status: "ok", session_id: "s", requested_session_id: "s", run_id: "run", question_id: "q", answer: "Use 6 mm stock", accepted: true, answered_by: "self" } });
  expect(currentTurn(s.get("s"))).toMatchObject({ status: "Working", canSend: false });
  expect(askContent(row, s.get("s").answers["q"]).answer).toBe("Use 6 mm stock");
  s.draft("s", "newer draft");
  s.snapshot("s", { ...idle, version: 3, run_id: "run", terminal: { run_id: "run", terminal_id: "t", state: "completed" } }, s.ticket());
  expect(currentTurn(s.get("s"))).toMatchObject({ status: "Completed", canSend: false });
  s.finish("s", attempt.id, "settled");
  expect(s.get("s").draft.text).toBe("newer draft");
  expect(attempt).toMatchObject({ submitted: { text: "immutable attempt" }, sessionId: "s", modelRevision: modelState.revision, context: { part: "tread" } });
});
it("late answer evidence outranks an uncertain receipt without automatic re-answer", () => {
  const { s, row } = fixture();
  s.beginAnswer("s", row);
  s.answer("s", "q", { phase: "refused", reason: "transport_error", message: "lost response" });
  expect(currentTurn(s.get("s")).status).toBe("Checking");
  expect(s.beginAnswer("s", row)).toBe(false);
  s.frame({ session_id: "s", run_id: "run", seq: 2, kind: "answer", payload: { question_id: "q", answer: "Use 6 mm stock" } });
  expect(currentTurn(s.get("s")).status).toBe("Working");
  const c = s.get("s");
  const updated = panelRows(c.history.items, c.live.entries).find(r => r.row === "ask")!;
  if (updated.row !== "ask") throw new Error("question missing");
  expect(askContent(updated, c.answers["q"])).toMatchObject({ answered: true, answeredBy: null });
});
it("a stale rendered question cannot answer after a live accepted answer arrives", () => {
  const { s, row } = fixture();
  s.frame({ session_id: "s", run_id: "run", seq: 2, kind: "answer", payload: { question_id: "q", answer: "Use 6 mm stock" } });
  expect(currentTurn(s.get("s")).status).toBe("Working");
  expect(s.beginAnswer("s", row)).toBe(false);
});
it("Stop requested does not settle or unlock; stale question/Stop cannot target a successor", () => {
  const { s, row } = fixture();
  s.stop("s", "run");
  expect(currentTurn(s.get("s"))).toMatchObject({ status: "Stop requested", canSend: false, canAnswer: false });
  expect(s.beginAnswer("s", row)).toBe(false);
  s.snapshot("s", { ...active, version: 4, run_id: "successor", active_run_id: "successor" }, s.ticket());
  s.stop("s", "run");
  expect(currentTurn(s.get("s"))).toMatchObject({ status: "Working", runId: "successor", stopRequested: false });
  expect(s.beginAnswer("s", row)).toBe(false);
});
it("a reopened call only binds to active ownership via recorded turn/run evidence; it cannot invent an answer address", () => {
  const s = createConversationStore();
  s.modelSnapshot("s", modelState, active, s.ticket());
  s.update("s", c => ({ ...c, history: { ...c.history,
    items: [historicalItem({ run_id: "s", seq: 0, turn: 2, kind: "tool_call", tool_call_id: "ask", payload: { name: "ask_user", arguments: { question: "Which?", options: ["A"] } } }, "s")],
    userPrompts: [{ turn: 2, seq: 0, run_id: "run", text: "ask first" }],
  } }));
  expect(currentTurn(s.get("s"))).toMatchObject({ status: "Checking", runId: "run", questionId: null, canSend: false });
  expect(currentTurn(s.get("s")).reason).toContain("live question could not be recovered");
  s.snapshot("s", { ...active, version: 3, run_id: "other", active_run_id: "other" }, s.ticket());
  expect(currentTurn(s.get("s")).status).toBe("Working");
});
it("renders structured recorded selections readably without inventing provenance", () => {
  expect(readableAnswer({ option_label: "Use 6 mm stock", option_index: 1 })).toBe("Use 6 mm stock");
  expect(readableAnswer({ option_labels: ["A", "B"] })).toBe("A, B");
  expect(readableAnswer({ text: "my words" })).toBe("my words");
  expect(readableAnswer({ unknown: "opaque" })).toBeNull();
  expect(readableAnswer(false)).toBe("false");
});
it("extracts readable failure causes and sanitizes technical envelopes", () => {
  const reason = '400: {"error":{"message":"The comparison was refused.","token":"private-value","url":"https://private.invalid/path"}}';
  expect(readableReason({ error: reason })).toBe("The comparison was refused.");
  const detail = sanitizeDiagnostic({ error: reason, authorization: "Bearer other-private", nested: { password: "nested-private" } });
  expect(detail).toContain("[redacted]");
  expect(detail).not.toContain("private-value");
  expect(detail).not.toContain("private.invalid");
  expect(detail).not.toContain("nested-private");
  expect(detail).not.toContain("other-private");
  expect(readableReason('400: {"message":"The comparison was refused. No design changed."}')).toBe("The comparison was refused.");
  expect(sanitizeDiagnostic("Bearer private-token")).not.toContain("private-token");
});
