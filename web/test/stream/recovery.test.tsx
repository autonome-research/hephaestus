// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
import { afterEach, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { isLiveQuestions, type ExecutionSnapshot, type LiveQuestions } from "../../src/api/sessions";
import { conversationRows, createConversationStore, currentTurn, conversationStore, readSessionModel } from "../../src/stream/conversation";
import { askContent } from "../../src/stream/ask";
import { historicalItem } from "../../src/stream/transcript";
import { AskUserWidget } from "../../src/components/stream/AskUserWidget";
import { Transcript } from "../../src/components/stream/Transcript";
import { modelState } from "../fixtures/models";
import { TOKEN_STORAGE_KEY, dropToken } from "../../src/api/token";

const active: ExecutionSnapshot = { epoch: "e", version: 2, run_id: "r", active_run_id: "r", terminal: null, admission_available: false };
const questions: LiveQuestions = { revision: 1, unavailable_reason: null, pending: [{
  session_id: "s", run_id: "r", question_id: "q", question: "Which stock?", answered: false,
  options: [{ label: "Use 6 mm", consequence: "Increase slot width to 6 mm" }], allow_free_text: false, multi: false,
}] };
const terminal: ExecutionSnapshot = { ...active, version: 3, active_run_id: null, admission_available: true,
  terminal: { run_id: "r", terminal_id: "t", state: "completed" } };
const receipt = { status: "ok", session_id: "s", requested_session_id: "s", run_id: "r", question_id: "q", answer: "Use 6 mm", accepted: true, answered_by: "self" } as const;
function setup(s = createConversationStore()) {
  s.modelSnapshot("s", modelState, active, s.ticket(), questions);
  s.update("s", c => ({ ...c, history: { ...c.history, state: "complete", items: [historicalItem({ run_id: "s", turn: 0, seq: 0, kind: "tool_call", tool_call_id: "not-an-address",
    payload: { name: "ask_user", arguments: { question: "Which stock?", options: ["Use 6 mm"], allow_free_text: false } } }, "s")], userPrompts: [{ turn: 0, seq: 0, text: "ask first", run_id: "r" }] } }));
  s.draft("s", "private next draft");
  s.toggleContext("s", "view");
  return s;
}
function recovered(s: ReturnType<typeof createConversationStore>) {
  const row = conversationRows(s.get("s")).find(r => r.row === "ask" && r.source === "live_state");
  if (!row || row.row !== "ask") throw new Error("no recovered question");
  return row;
}
afterEach(() => { dropToken(); conversationStore.reset(); vi.unstubAllGlobals(); });

it("validates explicit session/run authority and exact flags, refusing malformed/ambiguous/terminal projections", () => {
  expect(isLiveQuestions(questions, "s", active)).toBe(true);
  expect(isLiveQuestions(undefined, "s", active)).toBe(false);
  expect(isLiveQuestions(questions, "foreign", active)).toBe(false);
  expect(isLiveQuestions(questions, "s", terminal)).toBe(false);
  for (const patch of [{ multi: undefined }, { allow_free_text: undefined }, { run_id: "child" }, { question_id: "" }, { options: [{}] }, { answered: true }]) {
    expect(isLiveQuestions({ ...questions, pending: [{ ...questions.pending[0], ...patch }] }, "s", active)).toBe(false);
  }
  expect(isLiveQuestions({ ...questions, pending: [...questions.pending, ...questions.pending] }, "s", active)).toBe(false);
});
it("restores one explicit live card without inventing event identity or enabling the historical call", () => {
  const s = setup(conversationStore);
  const rows = conversationRows(s.get("s"));
  expect(rows.filter(r => r.row === "ask")).toHaveLength(2);
  const row = recovered(s);
  expect(row.question).toBeNull();
  expect(row.call).toBeNull();
  expect(currentTurn(s.get("s"))).toMatchObject({ status: "Waiting for your answer", questionId: "q", canSend: false });
  const markup = renderToStaticMarkup(<AskUserWidget row={row} />);
  const doc = new DOMParser().parseFromString(markup, "text/html");
  expect(markup).toContain("Recovered from the live run");
  expect(markup).toContain("Increase slot width to 6 mm");
  expect(doc.querySelector("[data-widget-source=live_state]")?.hasAttribute("data-event-id")).toBe(false);
  expect(doc.querySelector("[data-ask-text]")).toBeNull();
  expect(s.beginAnswer("foreign", row)).toBe(false);
  expect(s.beginAnswer("s", row)).toBe(true);
  expect(s.beginAnswer("s", row)).toBe(false);
});

it.each(["begin", "accepted", "answer-event", "terminal-event", "terminal-read", "stop", "successor", "epoch"])("late pending read cannot beat %s evidence or clear later draft/context", kind => {
  const s = setup();
  const row = recovered(s);
  const ticket = s.ticket();
  if (kind === "begin") s.beginAnswer("s", row);
  if (kind === "accepted") s.answer("s", "q", { phase: "settled", document: receipt });
  if (kind === "answer-event") s.frame({ session_id: "s", run_id: "r", seq: 2, kind: "answer", payload: { question_id: "q", answer: "Use 6 mm" } });
  if (kind === "terminal-event") s.frame({ session_id: "s", run_id: "r", seq: 3, kind: "terminal", payload: { state: "completed" } });
  if (kind === "terminal-read") s.snapshot("s", terminal, s.ticket());
  if (kind === "stop") s.stop("s", "r");
  if (kind === "successor" || kind === "epoch") s.modelSnapshot("s", modelState,
    { ...active, epoch: kind === "epoch" ? "new-epoch" : "e", version: 4, run_id: "next", active_run_id: "next" }, s.ticket(), { ...questions, revision: 2, pending: [] });
  s.modelSnapshot("s", modelState, active, ticket, questions);
  expect(s.beginAnswer("s", row)).toBe(false);
  // Only the actual terminal read carries positive admission; a stale read
  // must not remove that terminal or create admission in the other cases.
  expect(currentTurn(s.get("s")).canSend).toBe(kind === "terminal-read");
  expect(s.get("s").draft.text).toBe("private next draft");
  expect(s.get("s").contextDropped.has("view")).toBe(true);
});
it("recovery identity includes epoch even if an address is repeated; old content cannot answer the new shape", () => {
  const s = setup();
  const oldRow = recovered(s);
  s.modelSnapshot("s", modelState, { ...active, epoch: "new" }, s.ticket(), {
    ...questions, pending: [{ ...questions.pending[0]!, options: ["Different new-epoch option"] }],
  });
  const rows = conversationRows(s.get("s")).filter(r => r.row === "ask" && r.source === "live_state");
  expect(rows).toHaveLength(2);
  expect(new Set(rows.map(r => r.key)).size).toBe(2);
  expect(s.beginAnswer("s", oldRow)).toBe(false);
  const fresh = rows.find(r => r.row === "ask" && r.recovery?.epoch === "new")!;
  if (fresh.row !== "ask") throw new Error("missing new epoch");
  expect(askContent(fresh).options[0]?.label).toBe("Different new-epoch option");
  expect(s.beginAnswer("s", fresh)).toBe(true);
});
it("same execution version older registry revision cannot resurrect an absent question or invent an answer", () => {
  const s = setup();
  s.modelSnapshot("s", modelState, active, s.ticket(), { ...questions, revision: 3, pending: [] });
  s.modelSnapshot("s", modelState, active, s.ticket(), { ...questions, revision: 2 });
  expect(currentTurn(s.get("s"))).toMatchObject({ status: "Checking", canSend: false, questionId: null });
  expect(askContent(recovered(s)).answered).toBe(false);
  expect(s.beginAnswer("s", recovered(s))).toBe(false);
});
it("a newer empty registry snapshot visibly disables a retained real question as well as its write guard", () => {
  const s = setup();
  s.frame({ session_id: "s", run_id: "r", seq: 1, kind: "question", payload: questions.pending[0] });
  s.modelSnapshot("s", modelState, active, s.ticket(), { ...questions, revision: 2, pending: [] });
  const c = s.get("s");
  const doc = new DOMParser().parseFromString(renderToStaticMarkup(
    <Transcript rows={conversationRows(c)} currentTurn={currentTurn(c)} />), "text/html");
  const options = [...doc.querySelectorAll('[data-question-id="q"] [data-ask-option]')];
  expect(options.length).toBeGreaterThan(0);
  expect(options.every(option => option.getAttribute("aria-disabled") === "true")).toBe(true);
  expect(currentTurn(c)).toMatchObject({ status: "Checking", questionId: null, canSend: false });
});
it("terminal tombstone beats even a later read ticket; an answer receipt is not completion", () => {
  const s = setup();
  s.answer("s", "q", { phase: "settled", document: receipt });
  expect(currentTurn(s.get("s"))).toMatchObject({ status: "Working", canSend: false });
  s.frame({ session_id: "s", run_id: "r", seq: 3, kind: "terminal", payload: { state: "completed" } });
  s.modelSnapshot("s", modelState, active, s.ticket(), questions);
  expect(s.beginAnswer("s", recovered(s))).toBe(false);
  s.modelSnapshot("s", modelState, terminal, s.ticket(), { ...questions, revision: 2, pending: [] });
  expect(currentTurn(s.get("s"))).toMatchObject({ status: "Completed", canSend: true });
  expect(askContent(recovered(s), s.get("s").answers["q"]).answer).toBe("Use 6 mm");
});
it("late real question/answer join only their explicit address with one answer target and neutral attribution", () => {
  const s = setup();
  s.frame({ session_id: "s", run_id: "r", seq: 1, kind: "question", payload: questions.pending[0] });
  s.frame({ session_id: "s", run_id: "r", seq: 2, kind: "answer", payload: { question_id: "q", answer: "Use 6 mm" } });
  const rows = conversationRows(s.get("s")).filter(r => r.row === "ask" && askContent(r).questionId === "q");
  expect(rows).toHaveLength(1);
  const row = rows[0]!;
  if (row.row !== "ask") throw new Error("missing ask");
  expect(askContent(row)).toMatchObject({ answered: true, answeredBy: null });
  expect(currentTurn(s.get("s")).status).toBe("Working");
});
it("failed recovery retains held content/known Stop target and gates Send without inventing an actor", async () => {
  const s = setup(conversationStore);
  window.sessionStorage.setItem(TOKEN_STORAGE_KEY, "disposable-test-token");
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  await readSessionModel("s");
  // A newer listing can reconcile execution, not repair the failed question/model read.
  s.snapshot("s", active, s.ticket());
  expect(currentTurn(s.get("s"))).toMatchObject({ status: "Checking", runId: "r", canSend: false, canAnswer: false });
  expect(currentTurn(s.get("s")).reason).toContain("Checking the live question");
  expect(askContent(recovered(s))).toMatchObject({ question: "Which stock?", answered: false, answeredBy: null });
  expect(s.get("s").draft.text).toBe("private next draft");
  expect(s.beginAnswer("s", recovered(s))).toBe(false);
  s.transport("s", "reconnecting");
  const stale = s.ticket();
  s.frame({ session_id: "s", run_id: "r", seq: 2, kind: "answer", payload: { question_id: "q", answer: "Use 6 mm" } });
  s.modelSnapshot("s", modelState, active, stale, questions);
  expect(s.beginAnswer("s", recovered(s))).toBe(false);
});
