// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Project-lifetime, session-keyed evidence and explicit model reservation.
// No automatic writes, retries, or scheduler.
import { useSyncExternalStore } from "react";
import { fetchSessions, fetchSessionModel, selectSessionModel, isSessionModelState, isExecutionSnapshot,
  type SessionModelState, type ExecutionSnapshot, type PromptDocument, type LiveQuestions, type LiveQuestion } from "../api/sessions";
import { WorkspaceError } from "../api/client";
import type { ModelRef, ModelsDocument, ModelOption, ModelRevision } from "../api/providers";
import { sameModel } from "./composerChrome";
import { copy } from "../copy";
import { readTerminal, isTerminalState, type EventFrame } from "../api/events";
import { askContent, ASK_POST_IDLE, type AskPost, type AskRowLike } from "./ask";
import { panelRows, type PanelRow } from "./transcript";
import { outcomeLabel, readableReason } from "./outcome";
import type { ContextEnvelope, ContextMember } from "../api/sessions";
import { emptyHistory, type HistoryProgress } from "./history";
import { appendEcho, emptyLive, receive, refuseEcho, disconnected, resync, type LiveState } from "./live";

export interface Draft { readonly text: string; readonly revision: number }
export interface SendAttempt {
  readonly id: number;
  readonly submitted: Draft;
  readonly phase: "sending" | "settled" | "refused" | "unknown";
  readonly reason?: string;
  readonly holderSession?: string;
  readonly holderRun?: string;
  readonly baselineRunId?: string | null;
  readonly sessionId?: string | null;
  readonly modelRevision?: ModelRevision;
  readonly context?: ContextEnvelope;
}
export interface StopDelivery {
  readonly id: number;
  readonly runId: string;
  readonly epoch: string;
  readonly phase: "sending" | "uncertain" | "acknowledged";
}
export interface Conversation {
  readonly draft: Draft;
  /** Next-message preferences belong to the session, not panel visibility. */
  readonly contextDropped: ReadonlySet<ContextMember>;
  readonly contextAdded: ReadonlySet<ContextMember>;
  readonly answers: Readonly<Record<string, AskPost>>;
  readonly recovered: readonly (LiveQuestion & { readonly epoch: string })[];
  readonly liveQuestions: (LiveQuestions & { readonly epoch: string }) | null;
  readonly recoveryChecking: boolean;
  readonly closedRuns: ReadonlySet<string>;
  readonly model: SessionModelState | null;
  readonly modelChecking: boolean;
  readonly modelPending: boolean;
  readonly modelError: string | null;
  readonly modelBarrier: number;
  /** Only used on the null-session record. Existing choices never update it. */
  readonly proposal: ModelOption | null;
  readonly proposalInitialized: boolean;
  readonly proposalIsDefault: boolean;
  readonly attempt: SendAttempt | null;
  readonly execution: ExecutionSnapshot | null;
  readonly checking: boolean;
  readonly stopRequested: string | null;
  readonly stopDelivery: StopDelivery | null;
  readonly history: HistoryProgress;
  readonly live: LiveState;
  /** Local evidence barrier: reads begun before a write cannot settle it. */
  readonly barrier: number;
}
export interface CurrentTurn {
  readonly status: "Working" | "Completed" | "Cancelled" | "Request failed" | "Interrupted" | "Checking" | "Waiting for your answer" | "Recording answer" | "Sending request" | "Stop requested" | null;
  readonly questionId?: string | null;
  readonly reason: string | null;
  readonly runId: string | null;
  readonly canSend: boolean;
  readonly canAnswer: boolean;
  readonly terminalRunId: string | null;
  readonly stopRequested: boolean;
  readonly canRetryStop?: boolean;
  readonly stopNote?: string | null;
}
const EMPTY: Conversation = {
  draft: { text: "", revision: 0 }, contextDropped: new Set(), contextAdded: new Set(),
  answers: {}, recovered: [], liveQuestions: null, recoveryChecking: false, closedRuns: new Set(),
  attempt: null, execution: null,
  checking: true, stopRequested: null, stopDelivery: null, history: emptyHistory(),
  live: emptyLive("reconnecting"), barrier: 0,
  model: null, modelChecking: true, modelPending: false, modelError: null, modelBarrier: 0,
  proposal: null, proposalInitialized: false, proposalIsDefault: true,
};
/** Historical event IDs stay in their namespace; only the prompt's explicit
 * turn→run binding may relate a recorded question to execution ownership. */
export function questionRunId(c: Conversation, row: AskRowLike): string | null {
  if (row.recovery) return row.recovery.run_id;
  const anchor = row.question ?? row.call ?? row.answer;
  if (!anchor) return null;
  return anchor.surface === "historical" && anchor.turn !== null
    ? c.history.userPrompts.find(prompt => prompt.turn === anchor.turn)?.run_id ?? null
    : anchor.runId;
}
/** Keep archived rows unchanged. Only an explicit live question ID joins a
 * recovery read to a live row; text/tool resemblance never joins history. */
export function conversationRows(c: Conversation, sid?: string | null): readonly PanelRow[] {
  const rows = [...panelRows(c.history.items, c.live.entries, visiblePrompts(c), sid)];
  for (const recovery of c.recovered) {
    const index = rows.findIndex(row => recovery.epoch === c.execution?.epoch && row.row === "ask" && askContent(row).questionId === recovery.question_id
      && questionRunId(c, row) === recovery.run_id && (!row.recovery || row.recovery.epoch === recovery.epoch));
    const existing = rows[index];
    if (existing?.row === "ask") {
      if (existing.question === null) rows[index] = { ...existing, source: "live_state", recovery };
    } else rows.push({ row: "ask", key: `recovery:${recovery.epoch}:${recovery.run_id}:${recovery.question_id}`,
      source: "live_state", recovery, question: null, call: null, result: null, answer: null, status: "running" });
  }
  return rows;
}
function pendingAtRead(c: Conversation, row: AskRowLike): boolean {
  if (c.recoveryChecking || (row.recovery && row.recovery.epoch !== c.execution?.epoch)) return false;
  const q = askContent(row);
  if (c.closedRuns.has(questionRunId(c, row) ?? "")) return false;
  if (c.liveQuestions === null) return row.source !== "live_state";
  return c.liveQuestions.epoch === c.execution?.epoch && c.liveQuestions.unavailable_reason === null
    && c.liveQuestions.pending.some(p => p.question_id === q.questionId && p.run_id === questionRunId(c, row));
}
export function currentTurn(c: Conversation, selected = true): CurrentTurn {
  const e = c.execution;
  const active = e?.active_run_id ?? null;
  const terminal = e?.terminal;
  const uncertain = c.checking || e === null || c.attempt?.phase === "unknown";
  let status: CurrentTurn["status"] = null;
  let reason: string | null = null;
  const pending = c.attempt?.phase === "sending";
  const newTerminal = terminal && terminal.run_id === e?.run_id
    && (!pending || terminal.run_id !== c.attempt?.baselineRunId);
  // A known terminal settles the outcome, not project admission. In particular,
  // a terminal frame must not leave Stop visible while its read is in flight.
  if (newTerminal && active === null && !pending) {
    status = outcomeLabel(terminal.state) as CurrentTurn["status"];
    reason = readableReason(terminal.payload);
  }
  else if (selected && uncertain) {
    status = pending && active === null ? "Sending request" : "Checking";
    if (c.recoveryChecking && c.recovered.some(q => q.run_id === active)) reason = copy.stream.ask.recoveryChecking;
  }
  else if (active !== null) status = c.stopRequested === active ? "Stop requested" : "Working";
  else if (newTerminal) {
    status = outcomeLabel(terminal.state) as CurrentTurn["status"];
    reason = readableReason(terminal.payload);
  } else if (pending) {
    status = "Checking";
    reason = "Checking whether the request started. Nothing will be sent again.";
  } else if (e?.run_id) status = "Checking";
  else if (selected && (c.modelChecking || c.model?.state !== "ready")) {
    status = "Checking";
    reason = c.modelError ?? copy.models.checking;
  }
  let questionId: string | null = null;
  if (active !== null && !uncertain && c.stopRequested !== active) {
    for (const row of conversationRows(c)) {
      if (row.row !== "ask" || questionRunId(c, row) !== active) continue;
      const initial = askContent(row);
      const content = askContent(row, initial.questionId === null ? ASK_POST_IDLE : c.answers[initial.questionId]);
      if (content.state === "submitting" || (content.state === "answerable" && pendingAtRead(c, row))) {
        questionId = content.questionId;
        status = content.state === "submitting" ? "Recording answer" : "Waiting for your answer";
      } else if (!content.answered && content.state !== "abandoned"
        && !(row.source === "tool_result" && c.recovered.some(q => q.run_id === active))) {
        status = "Checking";
        reason = content.refusal ? "Checking whether the answer was recorded; nothing will be sent again."
          : row.source === "live_state" || c.recoveryChecking ? copy.stream.ask.recoveryChecking
          : "The live question could not be recovered. You can stop the known run.";
      }
    }
  }
  const delivery = active !== null && c.stopDelivery?.runId === active && c.stopDelivery.epoch === e?.epoch
    ? c.stopDelivery : null;
  const canRetryStop = delivery?.phase === "uncertain" && !uncertain && !c.closedRuns.has(active ?? "");
  if (delivery?.phase === "uncertain") status = "Checking";
  const blocked = c.attempt?.phase === "sending" || c.attempt?.phase === "unknown";
  return {
    status, reason, questionId, runId: active,
    canSend: !blocked && !c.modelPending && (selected
      ? !c.modelChecking && c.model?.state === "ready" && c.model.current !== null
        && !uncertain && e?.admission_available === true
      : c.proposal?.available === true),
    canAnswer: !uncertain && !c.recoveryChecking && active !== null && !c.closedRuns.has(active) && c.stopRequested !== active,
    terminalRunId: terminal?.run_id === e?.run_id ? terminal?.run_id ?? null : null,
    stopRequested: active !== null && c.stopRequested === active,
    canRetryStop,
    stopNote: delivery?.phase === "uncertain" ? copy.composer.stopUncertain
      : delivery?.phase === "acknowledged" ? copy.composer.stopAcknowledged : null,
  };
}

/** Projection only: retain archived evidence, but never label a linked active turn terminal. */
export function visiblePrompts(c: Conversation) {
  return c.history.userPrompts.map(prompt => {
    if (prompt.run_id === undefined || prompt.run_id !== c.execution?.active_run_id) return prompt;
    const { outcome: _outcome, ...open } = prompt;
    return open;
  });
}

export function createConversationStore() {
  const records = new Map<string, Conversation>();
  const listeners = new Set<() => void>();
  let clock = 0;
  let attemptId = 0;
  const key = (sid: string | null) => sid ?? "";
  const get = (sid: string | null): Conversation => records.get(key(sid)) ?? EMPTY;
  const update = (sid: string | null, fn: (c: Conversation) => Conversation) => {
    records.set(key(sid), fn(get(sid)));
    for (const listener of listeners) listener();
  };
  return {
    get, update,
    reset() { records.clear(); clock = 0; attemptId = 0; for (const listener of listeners) listener(); },
    subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener); }; },
    ticket: () => ++clock,
    draft(sid: string | null, text: string) {
      update(sid, c => ({ ...c, draft: { text, revision: c.draft.revision + 1 } }));
    },
    toggleContext(sid: string | null, member: ContextMember) {
      update(sid, c => {
        const contextDropped = new Set(c.contextDropped);
        if (!contextDropped.delete(member)) contextDropped.add(member);
        return { ...c, contextDropped };
      });
    },
    addCurrentView(sid: string | null, hasSelection: boolean) {
      update(sid, c => {
        const contextDropped = new Set(c.contextDropped);
        const contextAdded = new Set(c.contextAdded);
        for (const member of hasSelection ? ["view", "selection"] as const : ["view"] as const) {
          contextDropped.delete(member);
          contextAdded.add(member);
        }
        return { ...c, contextDropped, contextAdded };
      });
    },
    beginAnswer(sid: string, row: AskRowLike): boolean {
      const c = get(sid);
      const content = askContent(row);
      const id = content.questionId;
      const turn = currentTurn(c);
      if (id === null || content.sessionId !== sid || !turn.canAnswer
        || turn.questionId !== id || turn.status !== "Waiting for your answer"
        || turn.runId !== questionRunId(c, row) || !pendingAtRead(c, row)
        || askContent(row, c.answers[id]).state !== "answerable") return false;
      update(sid, c => ({ ...c, barrier: ++clock, answers: { ...c.answers, [id]: { phase: "sending" } } }));
      return true;
    },
    answer(sid: string, id: string, post: AskPost) {
      update(sid, c => ({ ...c, barrier: ++clock, answers: { ...c.answers, [id]: post } }));
    },
    begin(sid: string | null, context?: ContextEnvelope, reviewedModelRevision?: ModelRevision): SendAttempt | null {
      const c = get(sid);
      if (!currentTurn(c, sid !== null).canSend) return null;
      const attempt: SendAttempt = { id: ++attemptId, submitted: c.draft, phase: "sending",
        baselineRunId: c.execution?.run_id ?? null, sessionId: sid,
        ...(reviewedModelRevision ? { modelRevision: reviewedModelRevision } : c.model ? { modelRevision: c.model.revision } : {}), ...(context ? { context } : {}) };
      update(sid, c => ({ ...c, attempt, checking: true, barrier: ++clock, stopRequested: null, stopDelivery: null }));
      return attempt;
    },
    catalog(document: ModelsDocument) {
      update(null, c => {
        // Freeze the exact initial proposal; a refreshed catalog never substitutes another pair.
        const choice = c.proposalInitialized ? c.proposal : document.proposed_default;
        const option = document.providers.flatMap(p => p.models).find(m => sameModel(m, choice));
        return { ...c, proposalInitialized: true, proposal: choice === null ? null
          : option ?? { ...choice, name: choice.name,
            input: null, available: false, unavailable_reason: "model_not_configured" } };
      });
    },
    propose(model: ModelOption) {
      if (!model.available || get(null).modelPending || get(null).attempt?.phase === "sending") return;
      update(null, c => ({ ...c, proposal: model, proposalInitialized: true, proposalIsDefault: false }));
    },
    beginModel(sid: string): ModelRevision | null {
      const c = get(sid);
      if (!canSelectModel(c) || c.model === null) return null;
      const revision = c.model.revision;
      update(sid, c => ({ ...c, modelPending: true, modelError: null, modelBarrier: ++clock, barrier: clock }));
      return revision;
    },
    modelSnapshot(sid: string, model: SessionModelState, execution: ExecutionSnapshot | undefined, ticket: number, questions?: LiveQuestions) {
      update(sid, c => {
        if (ticket < c.modelBarrier || ticket < c.barrier) return c;
        const prior = c.model?.revision;
        if (prior?.epoch === model.revision.epoch && prior.version > model.revision.version) return c;
        const e = c.execution;
        const acceptExecution = execution !== undefined && !(e?.epoch === execution.epoch && e.version > execution.version)
          && !(execution.active_run_id && c.closedRuns.has(execution.active_run_id));
        if (questions && c.liveQuestions && c.liveQuestions.epoch === execution?.epoch && questions.revision < c.liveQuestions.revision) return c;
        const recovered = [...c.recovered];
        if (acceptExecution && questions) for (const q of questions.pending) {
          if (!recovered.some(old => old.epoch === execution.epoch && old.run_id === q.run_id && old.question_id === q.question_id)) recovered.push({ ...q, epoch: execution.epoch });
        }
        return { ...c, model, modelChecking: false, modelBarrier: ticket,
          ...(acceptExecution ? { execution, ...reconcileStop(c, execution), checking: false, barrier: ticket, recovered,
            liveQuestions: questions ? { ...questions, epoch: execution.epoch } : null,
            recoveryChecking: questions?.unavailable_reason != null,
            closedRuns: execution.terminal ? new Set([...c.closedRuns, execution.terminal.run_id]) : c.closedRuns,
          } : {}) };
      });
    },
    echo(sid: string, text: string) { update(sid, c => ({ ...c, live: appendEcho(c.live, text) })); },
    rejectEcho(sid: string, reason: string) { update(sid, c => ({ ...c, live: refuseEcho(c.live, reason) })); },
    finish(sid: string | null, id: number, phase: SendAttempt["phase"], data: Partial<SendAttempt> = {}) {
      if (get(sid).attempt?.id !== id) return;
      update(sid, c => c.attempt?.id !== id ? c : ({ ...c, checking: true, barrier: ++clock,
        attempt: { ...c.attempt, ...data, phase },
        draft: phase === "settled" && c.draft.revision === c.attempt.submitted.revision
          ? { text: "", revision: c.draft.revision + 1 } : c.draft,
      }));
      // The refusal names the HOLDER, not necessarily the attempted session.
      if (phase === "refused" && data.reason === "run_in_flight" && data.holderSession && data.holderRun) {
        const runId = data.holderRun;
        update(data.holderSession, c => c.execution?.active_run_id && c.execution.active_run_id !== runId
          ? { ...c, checking: true, barrier: ++clock }
          : ({ ...c, checking: false, barrier: ++clock,
          execution: { epoch: c.execution?.epoch ?? "refusal", version: c.execution?.version ?? 0,
            run_id: runId, active_run_id: runId, admission_available: false, terminal: null },
        }));
      }
    },
    snapshot(sid: string, execution: ExecutionSnapshot | undefined, ticket: number) {
      update(sid, c => {
        if (ticket < c.barrier || execution === undefined) return c;
        const prior = c.execution;
        if (prior?.epoch === execution.epoch && prior.version > execution.version) return c;
        if (execution.active_run_id && c.closedRuns.has(execution.active_run_id)) return c;
        return { ...c, execution, ...reconcileStop(c, execution), checking: false, barrier: ticket,
          closedRuns: execution.terminal ? new Set([...c.closedRuns, execution.terminal.run_id]) : c.closedRuns };
      });
    },
    unreconciled(ticket: number, present: readonly string[] = []) {
      for (const sid of records.keys()) {
        if (sid === "" || present.includes(sid)) continue;
        update(sid, c => ticket < c.barrier ? c : { ...c, checking: true, barrier: ticket });
      }
    },
    response(sid: string, document: PromptDocument) {
      update(sid, c => {
        const e = c.execution;
        // A late POST from A must never settle B. Always reconcile afterward.
        if (e?.run_id && e.run_id !== document.run_id) return c;
        // A reconciled terminal is the stored winner, not a POST's competing claim.
        if (e?.terminal?.run_id === document.run_id) return c;
        const state = document.terminal?.["state"] ?? document.run_status;
        if (typeof state !== "string" || !["completed", "cancelled", "failed", "interrupted"].includes(state)) return c;
        return { ...c, checking: false, stopRequested: null, stopDelivery: null,
          closedRuns: new Set([...c.closedRuns, document.run_id]), execution: {
          epoch: e?.epoch ?? "response", version: e?.version ?? 0,
          run_id: document.run_id, active_run_id: null, admission_available: true,
          terminal: { run_id: document.run_id, terminal_id: String(document.terminal?.["terminal_id"] ?? ""),
            state, payload: document.terminal?.["payload"] },
        } };
      });
    },
    frame(frame: EventFrame) {
      if (frame.session_id === null) return;
      update(frame.session_id, c => {
        const changed = (frame.kind === "terminal" && frame.run_id === c.execution?.run_id)
          || (frame.kind !== "terminal" && frame.run_id !== c.execution?.run_id && frame.run_id !== c.live.runId);
        const payload = frame.kind === "terminal" ? readTerminal(frame.payload) : null;
        const terminal = payload !== null && isTerminalState(payload.state) && frame.run_id === c.execution?.run_id
          && c.execution.terminal === null;
        return { ...c, live: receive(c.live, frame), checking: c.checking || changed,
          ...(terminal ? { stopRequested: null, stopDelivery: null, execution: { ...c.execution!,
            active_run_id: null, admission_available: false,
            terminal: { run_id: frame.run_id, terminal_id: payload.terminalId ?? "",
              state: payload.state!, payload: frame.payload },
          } } : {}),
          // Accepted answers and terminals are stronger than pending read snapshots.
          closedRuns: frame.kind === "terminal" ? new Set([...c.closedRuns, frame.run_id]) : c.closedRuns,
          ...(frame.kind === "question" ? { liveQuestions: null } : {}),
          barrier: changed || ["answer", "terminal", "question"].includes(frame.kind) ? ++clock : c.barrier };
      });
    },
    transport(sid: string, status: LiveState["status"]) {
      update(sid, c => ({ ...c, live: disconnected(c.live, status), checking: true, recoveryChecking: true, modelChecking: true, barrier: ++clock }));
    },
    gap(sid: string) { update(sid, c => ({ ...c, live: resync(c.live), checking: true })); },
    stop(sid: string, runId: string): StopDelivery | null {
      const c = get(sid);
      const turn = currentTurn(c);
      if (c.execution === null || turn.runId !== runId || c.closedRuns.has(runId)
        || (turn.stopRequested && !turn.canRetryStop)) return null;
      const delivery: StopDelivery = { id: ++clock, runId, epoch: c.execution.epoch, phase: "sending" };
      update(sid, c => ({ ...c, stopRequested: runId, stopDelivery: delivery, barrier: clock }));
      return delivery;
    },
    stopResult(sid: string, attempt: StopDelivery, phase: "uncertain" | "acknowledged") {
      update(sid, c => c.stopDelivery?.id !== attempt.id || c.execution?.active_run_id !== attempt.runId
        || c.execution.epoch !== attempt.epoch || c.closedRuns.has(attempt.runId) ? c
        : { ...c, stopDelivery: { ...attempt, phase }, checking: phase === "uncertain" || c.checking, barrier: ++clock });
    },
    needsRefresh() { return [...records.values()].some(c => c.checking || c.execution?.active_run_id || c.attempt?.phase === "sending" || c.attempt?.phase === "unknown"); },
  };
}
/** A read may retain intent only for the very same authoritative active run. */
function reconcileStop(c: Conversation, execution: ExecutionSnapshot) {
  return c.stopDelivery?.runId === execution.active_run_id && c.stopDelivery.epoch === execution.epoch
    && !c.closedRuns.has(c.stopDelivery.runId)
    ? {} : { stopRequested: null, stopDelivery: null };
}
export function canSelectModel(c: Conversation): boolean {
  return !c.modelPending && !c.modelChecking && !c.checking && c.model !== null
    && c.model.state !== "changing" && c.execution !== null && c.execution.active_run_id === null
    // Model unavailability is repairable, not execution uncertainty. Preserve
    // the unresolved-run gate without feeding model-only Checking back into it.
    && (c.execution.run_id === null || c.execution.terminal?.run_id === c.execution.run_id)
    && (c.execution.admission_available || c.model.state === "unavailable" || c.model.state === "uncertain")
    && c.attempt?.phase !== "sending" && c.attempt?.phase !== "unknown";
}
export const conversationStore = createConversationStore();

/** Selected-session read only; listing remains a no-probe projection. */
export async function readSessionModel(sid: string, checking = false): Promise<void> {
  const ticket = conversationStore.ticket();
  if (checking) conversationStore.update(sid, c => ({ ...c, modelChecking: true, recoveryChecking: true, modelBarrier: ticket }));
  try {
    const doc = await fetchSessionModel(sid);
    conversationStore.modelSnapshot(sid, doc.model_state, doc.execution, ticket, doc.live_questions);
    conversationStore.update(sid, c => c.modelBarrier !== ticket
      || !(c.modelError === copy.models.readFailed || (c.modelError === copy.models.lost && c.model?.state === "ready"))
      ? c : { ...c, modelError: null });
  } catch {
    conversationStore.update(sid, c => ticket < Math.max(c.barrier, c.modelBarrier) ? c
      : { ...c, checking: true, recoveryChecking: true, modelChecking: true, modelError: copy.models.readFailed, modelBarrier: ticket });
  }
}
/** Error extras are top-level on the wire (WorkspaceError.data preserves them). */
export function modelRefusal(sid: string, cause: unknown): void {
  if (!(cause instanceof WorkspaceError) || cause.data["session_id"] !== sid) return;
  const model = cause.data["model_state"];
  const execution = cause.data["execution"];
  if (isSessionModelState(model)) conversationStore.modelSnapshot(sid, model,
    isExecutionSnapshot(execution) ? execution : undefined, conversationStore.ticket());
}
export async function changeSessionModel(sid: string, model: ModelRef): Promise<void> {
  // Synchronous reservation before the first await, shared with Enter/form sends.
  const revision = conversationStore.beginModel(sid);
  if (revision === null) return;
  try {
    const doc = await selectSessionModel(sid, { model: { provider_id: model.provider_id, model_id: model.model_id },
      expected_model_revision: revision });
    // A GET begun during the write cannot subsequently undo its response.
    conversationStore.modelSnapshot(sid, doc.model_state, doc.execution, conversationStore.ticket());
    conversationStore.update(sid, c => ({ ...c, modelPending: false }));
  } catch (cause) {
    conversationStore.update(sid, c => ({ ...c, modelPending: false, modelChecking: true,
      modelBarrier: conversationStore.ticket(), modelError: cause instanceof WorkspaceError && !["timeout", "agent_unavailable", "transport_error"].includes(cause.reason)
        ? cause.reason === "model_changed" ? copy.models.changed : `${copy.models.unavailable}: ${cause.reason}`
        : copy.models.lost }));
    modelRefusal(sid, cause);
    // Never replay a write after transport loss or a conflict.
    await readSessionModel(sid);
  }
}
export function useConversation(sid: string | null): Conversation {
  return useSyncExternalStore(conversationStore.subscribe, () => conversationStore.get(sid), () => EMPTY);
}
/** Shared query function for the existing sessions key; no competing reducer. */
export async function readExecutionSessions() {
  const ticket = conversationStore.ticket();
  try {
    const document = await fetchSessions();
    for (const row of document.sessions) conversationStore.snapshot(row.session_id, row.execution, ticket);
    conversationStore.unreconciled(ticket, document.sessions.filter(row => row.execution !== undefined).map(row => row.session_id));
    return document;
  } catch (error) {
    // A failed read or disappeared session cannot leave stale admission enabled.
    conversationStore.unreconciled(ticket);
    throw error;
  }
}
