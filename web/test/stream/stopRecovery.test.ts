import { describe, expect, it } from "vitest";
import { createConversationStore, currentTurn, conversationRows } from "../../src/stream/conversation";
import type { ExecutionSnapshot } from "../../src/api/sessions";
import { modelState } from "../fixtures/models";

const active: ExecutionSnapshot = { epoch: "epoch", version: 2, run_id: "run", active_run_id: "run",
  admission_available: false, terminal: null };
const terminal: ExecutionSnapshot = { ...active, version: 3, active_run_id: null, admission_available: true,
  terminal: { run_id: "run", terminal_id: "terminal", state: "cancelled" } };
function setup() {
  const s = createConversationStore();
  s.modelSnapshot("s", modelState, active, s.ticket());
  s.draft("s", "next draft");
  s.toggleContext("s", "view");
  return s;
}
describe("Stop delivery recovery", () => {
  it("terminal before response immediately clears Stop without granting admission", () => {
    const s = setup();
    s.stop("s", "run");
    s.frame({ session_id: "s", run_id: "run", seq: 50, kind: "terminal", payload: { state: "cancelled" } });
    expect(currentTurn(s.get("s"))).toMatchObject({ status: "Cancelled", runId: null, stopRequested: false, canSend: false });
    expect(s.get("s").stopRequested).toBeNull();
    s.snapshot("s", active, s.ticket()); // even a later stale active read cannot reopen a closed run
    expect(currentTurn(s.get("s"))).toMatchObject({ status: "Cancelled", runId: null, canSend: false });
    s.snapshot("s", terminal, s.ticket());
    expect(currentTurn(s.get("s")).canSend).toBe(true);
  });
  it("a terminal settles a known new run even while its prompt response is pending", () => {
    const s = setup();
    s.snapshot("s", terminal, s.ticket());
    expect(s.begin("s")).not.toBeNull();
    s.snapshot("s", { ...active, version: 4, run_id: "next", active_run_id: "next" }, s.ticket());
    s.stop("s", "next");
    s.frame({ session_id: "s", run_id: "next", seq: 2, kind: "terminal", payload: { state: "cancelled" } });
    expect(currentTurn(s.get("s"))).toMatchObject({ status: "Cancelled", runId: null, canSend: false, stopRequested: false });
  });
  it("an older terminal cannot settle a new prompt whose delivery is unknown", () => {
    const s = setup();
    s.snapshot("s", terminal, s.ticket());
    const send = s.begin("s")!;
    s.finish("s", send.id, "unknown");
    s.snapshot("s", terminal, s.ticket());
    expect(currentTurn(s.get("s"))).toMatchObject({ status: "Checking", canSend: false, canRetryStop: false });
  });
  it.each(["request dropped", "response lost"])("%s is uncertain, retry requires a newer authoritative read", () => {
    const s = setup();
    const attempt = s.stop("s", "run")!;
    const stale = s.ticket();
    s.stopResult("s", attempt, "uncertain");
    expect(currentTurn(s.get("s"))).toMatchObject({ status: "Checking", canRetryStop: false, canAnswer: false });
    expect(s.stop("s", "run")).toBeNull();
    s.snapshot("s", active, stale);
    expect(currentTurn(s.get("s")).canRetryStop).toBe(false);
    s.snapshot("s", active, s.ticket());
    expect(currentTurn(s.get("s"))).toMatchObject({ status: "Checking", canRetryStop: true, canAnswer: false });
    const retry = s.stop("s", "run")!;
    expect(retry).not.toBe(attempt);
    expect(s.stop("s", "run")).toBeNull();
    s.stopResult("s", attempt, "acknowledged"); // stale attempt cannot settle retry
    expect(s.get("s").stopDelivery?.phase).toBe("sending");
    s.stopResult("s", retry, "acknowledged");
    expect(currentTurn(s.get("s"))).toMatchObject({ status: "Stop requested", canRetryStop: false, canSend: false });
    expect(s.get("s").draft.text).toBe("next draft");
    expect(s.get("s").contextDropped).toEqual(new Set(["view"]));
    expect(s.get("s").model).toBe(modelState);
  });
  it.each(["snapshot", "model", "frame", "response"])("%s terminal wins over late Stop callbacks", source => {
    const s = setup();
    const attempt = s.stop("s", "run")!;
    if (source === "snapshot") s.snapshot("s", terminal, s.ticket());
    if (source === "model") s.modelSnapshot("s", modelState, terminal, s.ticket());
    if (source === "frame") s.frame({ session_id: "s", run_id: "run", seq: 50, kind: "terminal", payload: { state: "cancelled" } });
    if (source === "response") s.response("s", { status: "ok", session_id: "s", run_id: "run", run_status: "cancelled", terminal: null, events: [], context: null });
    for (const result of ["uncertain", "acknowledged"] as const) s.stopResult("s", attempt, result);
    expect(currentTurn(s.get("s"))).toMatchObject({ status: "Cancelled", stopRequested: false, canRetryStop: false });
    expect(s.get("s").stopDelivery).toBeNull();
  });
  it.each([false, true])("waiting question Stop preserves first-write answer authority (answer first=%s)", answerFirst => {
    const s = setup();
    s.modelSnapshot("s", modelState, active, s.ticket(), { revision: 1, unavailable_reason: null, pending: [{
      session_id: "s", run_id: "run", question_id: "q", question: "Choose?",
      options: ["yes", "no"], allow_free_text: false, multi: false, answered: false,
    }] });
    const row = conversationRows(s.get("s")).find(row => row.row === "ask")!;
    if (row.row !== "ask") throw new Error("missing recovered question");
    expect(currentTurn(s.get("s")).status).toBe("Waiting for your answer");
    if (answerFirst) expect(s.beginAnswer("s", row)).toBe(true);
    const attempt = s.stop("s", "run")!;
    expect(s.beginAnswer("s", row)).toBe(false);
    s.stopResult("s", attempt, "uncertain");
    s.snapshot("s", active, s.ticket());
    expect(s.beginAnswer("s", row)).toBe(false);
    expect(currentTurn(s.get("s")).canRetryStop).toBe(true);
    if (answerFirst) {
      s.answer("s", "q", { phase: "settled", document: { status: "ok", session_id: "s", requested_session_id: "s",
        run_id: "run", question_id: "q", accepted: true, answered_by: "self", answer: "yes" } });
      expect(s.get("s").answers["q"]).toMatchObject({ phase: "settled", document: { accepted: true, answer: "yes" } });
    } else expect(s.get("s").answers).toEqual({});
    s.snapshot("s", terminal, s.ticket());
    expect(s.beginAnswer("s", row)).toBe(false);
  });
  it("reload recovers authority but never invents an earlier Stop acknowledgement", () => {
    const s = createConversationStore();
    expect(s.stop("s", "run")).toBeNull();
    s.modelSnapshot("s", modelState, active, s.ticket());
    expect(currentTurn(s.get("s"))).toMatchObject({ status: "Working", canRetryStop: false, stopRequested: false });
    expect(s.stop("s", "run")).not.toBeNull();
  });
  it("reconnect cannot enable retry; successor and epoch changes invalidate it", () => {
    const s = setup();
    const attempt = s.stop("s", "run")!;
    s.stopResult("s", attempt, "uncertain");
    s.transport("s", "live");
    expect(currentTurn(s.get("s")).canRetryStop).toBe(false);
    s.snapshot("s", active, s.ticket());
    expect(currentTurn(s.get("s")).canRetryStop).toBe(true);
    s.snapshot("s", { ...active, version: 4, run_id: "successor", active_run_id: "successor" }, s.ticket());
    s.stopResult("s", attempt, "uncertain");
    expect(s.stop("s", "run")).toBeNull();
    expect(currentTurn(s.get("s"))).toMatchObject({ status: "Working", runId: "successor", stopRequested: false, canRetryStop: false });
    const successorStop = s.stop("s", "successor");
    s.stopResult("s", attempt, "acknowledged");
    expect(s.get("s").stopDelivery).toBe(successorStop);
    s.snapshot("s", { ...active, epoch: "new-epoch" }, s.ticket());
    expect(s.get("s").stopDelivery).toBeNull();
  });
});
