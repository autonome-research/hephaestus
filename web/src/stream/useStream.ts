// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
// Selected-session binding. The project observer owns transport and execution;
// collapse/switch never discards drafts, attempts, event identities or gaps.
import { useCallback, useEffect, useState } from "react";
import { fetchHistoryPage, fetchThread, type ThreadDocument } from "../api/sessions";
import { loadHistory, type HistoryProgress } from "./history";
import { conversationStore, currentTurn, readSessionModel, useConversation, conversationRows, type CurrentTurn } from "./conversation";
import { sessionPromptStore } from "./sessionPrompts";
import { loadThreadTree, threadTabs, type ThreadTab } from "./thread";
import { type PanelRow, type StreamState } from "./transcript";

export interface StreamView {
  readonly rows: readonly PanelRow[];
  readonly status: StreamState;
  readonly currentTurn: CurrentTurn;
  readonly history: HistoryProgress;
  readonly tabs: readonly ThreadTab[];
  readonly threadState: ThreadDocument["thread_state"] | null;
  readonly threadBounded: boolean;
  readonly resyncs: number;
  readonly runId: string | null;
  readonly clearRunId: () => void;
  readonly echo: (sessionId: string, text: string) => void;
  readonly refuseEcho: (sessionId: string, reason: string) => void;
  readonly midRunAttach: boolean;
  readonly terminals: number;
  readonly error: Error | null;
}
const NO_TABS: readonly ThreadTab[] = [];
export function useStream(sessionId: string | null): StreamView {
  const conversation = useConversation(sessionId);
  const { history, live } = conversation;
  const turn = currentTurn(conversation, sessionId !== null);
  const [thread, setThread] = useState<{
    sid: string; document: ThreadDocument; bounded: boolean; tabs: readonly ThreadTab[];
  } | null>(null);
  const [error, setError] = useState<{ sid: string; error: Error } | null>(null);
  useEffect(() => {
    if (sessionId === null) return;
    const signal = { aborted: false };
    // Cached material belongs to this session for project lifetime.
    if (conversationStore.get(sessionId).history.state === "loading") {
      void loadHistory(sessionId, fetchHistoryPage, progress => {
        if (signal.aborted) return;
        conversationStore.update(sessionId, c => ({ ...c, history: progress }));
        for (const prompt of progress.userPrompts) {
          if (prompt.text !== null) sessionPromptStore.remember(sessionId, prompt.text);
        }
      }, signal);
    }
    void loadThreadTree(sessionId, fetchThread).then(tree => {
      if (!signal.aborted) setThread({ sid: sessionId, ...tree, tabs: threadTabs(tree.document) });
    }).catch((cause: unknown) => {
      if (!signal.aborted) setError({ sid: sessionId, error: cause instanceof Error ? cause : new Error(String(cause)) });
    });
    return () => { signal.aborted = true; };
  }, [sessionId]);

  // Refresh ONLY identifiable metadata. Never splice a historical event tail
  // into live events or use it to heal a transport gap. Tail pages include
  // outcome-only updates to older turns, even when no event was appended.
  const terminalId = conversation.execution?.terminal?.terminal_id;
  useEffect(() => {
    if (sessionId === null) return;
    const refresh = () => { void readSessionModel(sessionId, true); };
    refresh();
    // Idle polling is intentional: other clients can select without sending an event.
    const timer = window.setInterval(() => {
      if (document.visibilityState !== "hidden") void readSessionModel(sessionId);
    }, 5_000);
    window.addEventListener("focus", refresh);
    window.addEventListener("online", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
      window.removeEventListener("online", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [sessionId, terminalId, live.status]);
  useEffect(() => {
    if (sessionId === null || terminalId === undefined || history.endCursor == null) return;
    let attached = true;
    void fetchHistoryPage(sessionId, null, history.endCursor).then(page => {
      if (!attached) return;
      conversationStore.update(sessionId, c => ({ ...c, history: { ...c.history,
        userPrompts: c.history.userPrompts.map(prompt => {
          if (prompt.turn === undefined) return prompt;
          return page.user_prompts?.find(update => update.turn === prompt.turn) ?? prompt;
        }),
      } }));
    }).catch(() => { /* Retain the original frozen record, not invented outcomes. */ });
    return () => { attached = false; };
  }, [sessionId, terminalId, history.endCursor]);
  const clearRunId = useCallback(() => undefined, []); // execution reads own identity
  return {
    rows: conversationRows(conversation, sessionId),
    status: sessionId === null ? "historical" : live.status,
    currentTurn: turn, history,
    tabs: thread?.sid === sessionId ? thread.tabs : NO_TABS,
    threadState: thread?.sid === sessionId ? thread.document.thread_state : null,
    threadBounded: thread?.sid === sessionId ? thread.bounded : false,
    resyncs: live.resyncs, runId: turn.runId, clearRunId,
    echo: conversationStore.echo, refuseEcho: conversationStore.rejectEcho,
    midRunAttach: live.midRunAttach, terminals: live.terminals,
    error: error?.sid === sessionId ? error.error : history.error,
  };
}
