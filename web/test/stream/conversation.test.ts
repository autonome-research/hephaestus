import { describe, expect, it } from "vitest";
import { createConversationStore as emptyStore, currentTurn } from "../../src/stream/conversation";
import type { ExecutionSnapshot, PromptDocument } from "../../src/api/sessions";

import { modelState } from "../fixtures/models";
function createConversationStore() {
  const store = emptyStore();
  store.modelSnapshot("a", modelState, undefined, store.ticket());
  return store;
}
const idle: ExecutionSnapshot = { epoch: "server-1", version: 1, run_id: null,
  active_run_id: null, admission_available: true, terminal: null };
function active(run = "run-a", version = 2): ExecutionSnapshot {
  return { ...idle, version, run_id: run, active_run_id: run, admission_available: false };
}
function ended(run = "run-a", state = "completed", version = 3): ExecutionSnapshot {
  return { ...idle, version, run_id: run,
    terminal: { run_id: run, terminal_id: `terminal:${run}`, state, payload: { reason: "process lost" } } };
}
describe("project conversation evidence", () => {
  it("attaches before any frame; stale interrupted history is not current execution", () => {
    const store = createConversationStore();
    expect(currentTurn(store.get("a")).status).toBe("Checking");
    store.update("a", c => ({ ...c, history: { ...c.history, userPrompts: [
      { turn: 0, seq: 0, text: "old", outcome: { state: "interrupted" } },
    ] } }));
    store.snapshot("a", active(), store.ticket());
    expect(store.get("a").live.entries).toEqual([]);
    expect(currentTurn(store.get("a"))).toMatchObject({ status: "Working", runId: "run-a", canSend: false });
    expect(store.get("a").history.userPrompts[0]?.outcome?.state).toBe("interrupted");
  });
  it("empty means no fabricated status; missing old-server evidence remains Checking", () => {
    const store = createConversationStore();
    store.snapshot("a", undefined, store.ticket());
    expect(currentTurn(store.get("a")).status).toBe("Checking");
    store.snapshot("a", idle, store.ticket());
    expect(currentTurn(store.get("a"))).toMatchObject({ status: null, canSend: true });
  });
  it("disconnect/reconnect are not interruption; missed terminals reconcile from reads", () => {
    const store = createConversationStore();
    store.snapshot("a", active(), store.ticket());
    const stale = store.ticket();
    store.transport("a", "reconnecting");
    store.snapshot("a", ended(), stale);
    expect(currentTurn(store.get("a")).status).toBe("Checking");
    store.transport("a", "live");
    expect(currentTurn(store.get("a")).status).toBe("Checking");
    store.snapshot("a", ended(), store.ticket());
    expect(currentTurn(store.get("a")).canSend).toBe(false); // reconnect also needs model evidence
    store.modelSnapshot("a", modelState, ended(), store.ticket());
    expect(currentTurn(store.get("a"))).toMatchObject({ status: "Finished", runId: null, canSend: true });
  });
  it.each(["cancelled", "failed", "interrupted"])("requires real %s terminal evidence", state => {
    const store = createConversationStore();
    store.snapshot("a", active(), store.ticket());
    store.stop("a", "run-a");
    expect(currentTurn(store.get("a"))).toMatchObject({ status: "Working", stopRequested: true });
    store.snapshot("a", ended("run-a", state), store.ticket());
    expect(currentTurn(store.get("a"))).toMatchObject({ status: "Stopped", reason: "process lost", runId: null });
  });
  it("late terminal/POST for A and out-of-order reads cannot terminate B", () => {
    const store = createConversationStore();
    const oldTicket = store.ticket();
    store.snapshot("a", active("run-b", 4), store.ticket());
    store.frame({ session_id: "a", run_id: "run-a", seq: 2 ** 62, kind: "terminal", payload: { state: "completed" } });
    store.response("a", { run_id: "run-a", run_status: "completed", terminal: null } as PromptDocument);
    store.snapshot("a", ended(), oldTicket);
    expect(currentTurn(store.get("a"))).toMatchObject({ status: "Working", runId: "run-b" });
  });
  it("a pending send does not inherit the previous turn's terminal", () => {
    const store = createConversationStore();
    store.snapshot("a", ended(), store.ticket());
    store.draft("a", "next turn");
    store.begin("a");
    store.snapshot("a", ended(), store.ticket()); // admission read wins the race to POST
    expect(currentTurn(store.get("a"))).toMatchObject({ status: "Checking", canSend: false });
    store.snapshot("a", active("run-b", 4), store.ticket());
    expect(currentTurn(store.get("a"))).toMatchObject({ status: "Working", runId: "run-b" });
  });
  it("a late conflicting POST cannot replace the reconciled terminal winner", () => {
    const store = createConversationStore();
    store.snapshot("a", ended("run-a", "interrupted"), store.ticket());
    store.response("a", { run_id: "run-a", run_status: "completed", terminal: null } as PromptDocument);
    expect(currentTurn(store.get("a"))).toMatchObject({ status: "Stopped", reason: "process lost" });
  });
  it("failed/missing session reconciliation blocks stale admission without inventing a terminal", () => {
    const store = createConversationStore();
    const stale = store.ticket();
    store.snapshot("a", idle, store.ticket());
    store.unreconciled(stale);
    expect(currentTurn(store.get("a")).canSend).toBe(true);
    store.unreconciled(store.ticket());
    expect(currentTurn(store.get("a"))).toMatchObject({ status: "Checking", canSend: false });
    store.snapshot("a", active(), store.ticket());
    store.unreconciled(store.ticket(), ["a"]);
    expect(currentTurn(store.get("a")).status).toBe("Working");
    store.unreconciled(store.ticket());
    expect(currentTurn(store.get("a"))).toMatchObject({ status: "Checking", runId: "run-a" });
  });
  it("named rejection removes the provisional message and adopts only its holder", () => {
    const store = createConversationStore();
    store.snapshot("a", idle, store.ticket());
    store.draft("a", "my immutable words");
    const send = store.begin("a")!;
    store.echo("a", send.submitted.text);
    store.rejectEcho("a", "run_in_flight");
    store.finish("a", send.id, "refused", { reason: "run_in_flight", holderSession: "b", holderRun: "run-b" });
    expect(store.get("a").live.entries).toEqual([]);
    expect(store.get("a").draft.text).toBe("my immutable words");
    expect(currentTurn(store.get("a"))).toMatchObject({ status: "Checking", runId: null });
    expect(currentTurn(store.get("b"))).toMatchObject({ status: "Working", runId: "run-b" });
    store.snapshot("a", { ...idle, version: 5 }, store.ticket());
    expect(currentTurn(store.get("a")).canSend).toBe(true);
  });
  it("same-session refusal enables Stop and expires without a terminal frame", () => {
    const store = createConversationStore();
    store.snapshot("a", idle, store.ticket());
    const send = store.begin("a")!;
    store.finish("a", send.id, "refused", { reason: "run_in_flight", holderSession: "a", holderRun: "run-a" });
    expect(currentTurn(store.get("a"))).toMatchObject({ status: "Working", runId: "run-a" });
    store.snapshot("a", ended(), store.ticket());
    expect(currentTurn(store.get("a")).canSend).toBe(true);
  });
  it("draft revisions survive edits, switching and late responses", () => {
    const store = createConversationStore();
    store.snapshot("a", idle, store.ticket());
    store.draft("a", "send this");
    const send = store.begin("a")!;
    expect(store.begin("a")).toBeNull();
    store.draft("a", "send this"); // identical text, a NEW revision
    store.draft("b", "unrelated draft");
    store.finish("a", send.id, "settled");
    expect(store.get("a").draft.text).toBe("send this");
    expect(store.get("b").draft.text).toBe("unrelated draft");
    store.snapshot("a", idle, store.ticket());
    const next = store.begin("a")!;
    store.finish("a", send.id, "settled"); // stale completion cannot settle next
    expect(store.get("a").attempt?.id).toBe(next.id);
    expect(store.get("a").attempt?.phase).toBe("sending");
    store.finish("a", next.id, "settled");
    expect(store.get("a").draft.text).toBe("");
  });
  it("lost POST keeps immutable submission and draft, never retries", () => {
    const store = createConversationStore();
    store.snapshot("a", idle, store.ticket());
    store.draft("a", "uncertain");
    const send = store.begin("a")!;
    store.finish("a", send.id, "unknown");
    store.snapshot("a", idle, store.ticket());
    expect(store.begin("a")).toBeNull();
    expect(currentTurn(store.get("a"))).toMatchObject({ status: "Checking", canSend: false });
    expect(store.get("a").draft.text).toBe("uncertain");
  });
});
