// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Project-lifetime, session-keyed evidence and explicit model reservation.
// No automatic writes, retries, or scheduler.
import { useSyncExternalStore } from "react";
import { fetchSessions, fetchSessionModel, selectSessionModel, isSessionModelState, isExecutionSnapshot,
  type SessionModelState, type ExecutionSnapshot, type PromptDocument } from "../api/sessions";
import { WorkspaceError } from "../api/client";
import type { ModelRef, ModelsDocument, ModelOption, ModelRevision } from "../api/providers";
import { sameModel } from "./composerChrome";
import { copy } from "../copy";
import type { EventFrame } from "../api/events";
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
}
export interface Conversation {
  readonly draft: Draft;
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
  readonly history: HistoryProgress;
  readonly live: LiveState;
  /** Local evidence barrier: reads begun before a write cannot settle it. */
  readonly barrier: number;
}
export interface CurrentTurn {
  readonly status: "Working" | "Finished" | "Stopped" | "Checking" | null;
  readonly reason: string | null;
  readonly runId: string | null;
  readonly canSend: boolean;
  readonly canAnswer: boolean;
  readonly terminalRunId: string | null;
  readonly stopRequested: boolean;
}
const EMPTY: Conversation = {
  draft: { text: "", revision: 0 }, attempt: null, execution: null,
  checking: true, stopRequested: null, history: emptyHistory(),
  live: emptyLive("reconnecting"), barrier: 0,
  model: null, modelChecking: true, modelPending: false, modelError: null, modelBarrier: 0,
  proposal: null, proposalInitialized: false, proposalIsDefault: true,
};
function terminalReason(payload: unknown): string | null {
  if (payload === null || typeof payload !== "object") return null;
  const value = payload as Record<string, unknown>;
  const reason = value["error"] ?? value["reason"];
  return typeof reason === "string" ? reason : null;
}
export function currentTurn(c: Conversation, selected = true): CurrentTurn {
  const e = c.execution;
  const active = e?.active_run_id ?? null;
  const terminal = e?.terminal;
  const uncertain = c.checking || e === null || c.attempt?.phase === "unknown";
  let status: CurrentTurn["status"] = null;
  let reason: string | null = null;
  if (selected && uncertain) status = "Checking";
  else if (active !== null) status = "Working";
  else if (c.attempt?.phase === "sending") status = "Checking";
  else if (terminal && terminal.run_id === e?.run_id) {
    status = terminal.state === "completed" ? "Finished"
      : ["cancelled", "failed", "interrupted"].includes(terminal.state) ? "Stopped" : "Checking";
    reason = terminalReason(terminal.payload) ?? (status === "Stopped" ? terminal.state : null);
  } else if (e?.run_id) status = "Checking";
  const blocked = c.attempt?.phase === "sending" || c.attempt?.phase === "unknown";
  return {
    status, reason, runId: active,
    canSend: !blocked && !c.modelPending && (selected
      ? !c.modelChecking && c.model?.state === "ready" && c.model.current !== null
        && !uncertain && e?.admission_available === true
      : c.proposal?.available === true),
    canAnswer: !uncertain && active !== null,
    terminalRunId: terminal?.run_id === e?.run_id ? terminal?.run_id ?? null : null,
    stopRequested: active !== null && c.stopRequested === active,
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
    begin(sid: string | null): SendAttempt | null {
      const c = get(sid);
      if (!currentTurn(c, sid !== null).canSend) return null;
      const attempt: SendAttempt = { id: ++attemptId, submitted: c.draft, phase: "sending" };
      update(sid, c => ({ ...c, attempt, checking: true, barrier: ++clock, stopRequested: null }));
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
    modelSnapshot(sid: string, model: SessionModelState, execution: ExecutionSnapshot | undefined, ticket: number) {
      update(sid, c => {
        if (ticket < c.modelBarrier || ticket < c.barrier) return c;
        const prior = c.model?.revision;
        if (prior?.epoch === model.revision.epoch && prior.version > model.revision.version) return c;
        const e = c.execution;
        const acceptExecution = execution !== undefined && !(e?.epoch === execution.epoch && e.version > execution.version);
        return { ...c, model, modelChecking: false, modelBarrier: ticket,
          ...(acceptExecution ? { execution, checking: false, barrier: ticket } : {}) };
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
        return { ...c, execution, checking: false, barrier: ticket };
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
        return { ...c, checking: false, execution: {
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
        return { ...c, live: receive(c.live, frame), checking: c.checking || changed,
          barrier: changed ? ++clock : c.barrier };
      });
    },
    transport(sid: string, status: LiveState["status"]) {
      update(sid, c => ({ ...c, live: disconnected(c.live, status), checking: true, modelChecking: true, barrier: ++clock }));
    },
    gap(sid: string) { update(sid, c => ({ ...c, live: resync(c.live), checking: true })); },
    stop(sid: string, runId: string) {
      update(sid, c => c.execution?.active_run_id !== runId ? c : { ...c, stopRequested: runId });
    },
    needsRefresh() { return [...records.values()].some(c => c.checking || c.execution?.active_run_id || c.attempt?.phase === "sending" || c.attempt?.phase === "unknown"); },
  };
}
export function canSelectModel(c: Conversation): boolean {
  return !c.modelPending && !c.modelChecking && !c.checking && c.model !== null
    && c.model.state !== "changing" && c.execution !== null && c.execution.active_run_id === null
    && currentTurn(c).status !== "Checking"
    && (c.execution.admission_available || c.model.state === "unavailable" || c.model.state === "uncertain")
    && c.attempt?.phase !== "sending" && c.attempt?.phase !== "unknown";
}
export const conversationStore = createConversationStore();

/** Selected-session read only; listing remains a no-probe projection. */
export async function readSessionModel(sid: string, checking = false): Promise<void> {
  const ticket = conversationStore.ticket();
  if (checking) conversationStore.update(sid, c => ({ ...c, modelChecking: true, modelBarrier: ticket }));
  try {
    const doc = await fetchSessionModel(sid);
    conversationStore.modelSnapshot(sid, doc.model_state, doc.execution, ticket);
    conversationStore.update(sid, c => c.modelBarrier !== ticket
      || !(c.modelError === copy.models.readFailed || (c.modelError === copy.models.lost && c.model?.state === "ready"))
      ? c : { ...c, modelError: null });
  } catch {
    conversationStore.update(sid, c => ticket < Math.max(c.barrier, c.modelBarrier) ? c
      : { ...c, modelChecking: true, modelError: copy.models.readFailed, modelBarrier: ticket });
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
