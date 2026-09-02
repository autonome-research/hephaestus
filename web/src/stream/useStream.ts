// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The React binding for one session's transcript: history's prefix, the live
// socket's suffix, and the thread the tabs are drawn from (INTERFACE.md §7, §8).
//
// It contains no rules. Every decision — what a resync costs, where the seam
// goes, which absences are named, how a chip's status is derived — is made by
// the pure modules beside it and tested there. What lives here is the wiring
// those modules cannot have: effects, aborts, and the socket's lifetime.
//
// ORDER MATTERS AND IS DELIBERATE. History loads first and renders
// progressively; the socket attaches independently and appends. They are never
// merged (§8) — `panelRows` puts a visible seam between them — and history is
// never used to close a live gap (§2.7), which is why nothing here re-pages
// history after a resync.
//
// EVERY PIECE OF STATE IS TAGGED WITH THE SESSION IT BELONGS TO. Switching tabs
// must not show the previous session's transcript for even one frame, and the
// obvious fix — resetting state at the top of the effect — is a synchronous
// setState inside an effect, i.e. a cascading render. Tagging instead makes the
// reset a *derivation*: state for another session simply is not this session's
// state, and the empty values are module constants so the identity a `useMemo`
// depends on does not change every render.

import { useCallback, useEffect, useRef, useState } from "react";
import { fetchHistoryPage, fetchThread, type ThreadDocument } from "../api/sessions";
import { workspaceToken } from "../api/token";
import { emptyHistory, loadHistory, type HistoryProgress } from "./history";
import {
  appendEcho,
  clearLiveRun,
  disconnected,
  emptyLive,
  receive,
  resync,
  setStatus,
  type LiveState,
} from "./live";
import { eventsUrl, StreamSocket } from "./socket";
import { loadThreadTree, threadTabs, type ThreadTab } from "./thread";
import { panelRows, type PanelRow, type StreamState } from "./transcript";

/** One piece of state and the session it is about. */
interface Tagged<T> {
  readonly sid: string | null;
  readonly value: T;
}

interface ThreadState {
  readonly tabs: readonly ThreadTab[];
  readonly document: ThreadDocument | null;
  readonly bounded: boolean;
}

const NO_HISTORY: HistoryProgress = emptyHistory();
const NO_THREAD: ThreadState = { tabs: [], document: null, bounded: false };
const NO_STREAM: LiveState = emptyLive("historical");
const CONNECTING: LiveState = emptyLive("reconnecting");
const NO_TOKEN: LiveState = emptyLive("detached");

export interface StreamView {
  readonly rows: readonly PanelRow[];
  readonly status: StreamState;
  readonly history: HistoryProgress;
  readonly tabs: readonly ThreadTab[];
  readonly threadState: ThreadDocument["thread_state"] | null;
  readonly threadBounded: boolean;
  readonly resyncs: number;
  /** The run that is live *now* for this session — the composer's own (§7A.5). */
  readonly runId: string | null;
  /** Forget `runId` on submit so Cancel cannot target a finished turn. */
  readonly clearRunId: () => void;
  /**
   * §7A.5 (C1): append the local-prompt echo on Send — originating tab only,
   * because only this tab's composer calls it with text this tab holds.
   */
  readonly echo: (text: string) => void;
  /** Live `terminal` frames seen; §7A.11's read-refresh trigger. */
  readonly terminals: number;
  readonly error: Error | null;
}

/**
 * The transcript for one session.
 *
 * `sessionId === null` yields an empty view with `historical` status: no socket
 * is opened and no request is issued, because a panel with no session selected
 * has nothing to be live about.
 */
export function useStream(sessionId: string | null): StreamView {
  const [history, setHistory] = useState<Tagged<HistoryProgress>>({
    sid: null,
    value: NO_HISTORY,
  });
  const [thread, setThread] = useState<Tagged<ThreadState>>({ sid: null, value: NO_THREAD });
  const [live, setLive] = useState<Tagged<LiveState>>({ sid: null, value: NO_STREAM });
  const [error, setError] = useState<Tagged<Error | null>>({ sid: null, value: null });

  const token = workspaceToken();
  const baseline = sessionId === null ? NO_STREAM : token === null ? NO_TOKEN : CONNECTING;

  const shownHistory = history.sid === sessionId ? history.value : NO_HISTORY;
  const shownThread = thread.sid === sessionId ? thread.value : NO_THREAD;
  const shownLive = live.sid === sessionId ? live.value : baseline;
  const shownError = error.sid === sessionId ? error.value : null;

  // The socket reads the cursor at connect time, which can be several renders
  // after the last one it saw. A ref is the only way to hand it "now" rather
  // than the value captured when the effect ran; it is written in an effect
  // because a ref written during render is a render with a side effect.
  const cursorRef = useRef<LiveState["cursor"]>(null);
  useEffect(() => {
    cursorRef.current = shownLive.cursor;
  }, [shownLive.cursor]);

  // -- the historical prefix (§8) ----------------------------------------
  useEffect(() => {
    if (sessionId === null) return;
    const signal = { aborted: false };
    void loadHistory(
      sessionId,
      fetchHistoryPage,
      (progress) => {
        if (!signal.aborted) setHistory({ sid: sessionId, value: progress });
      },
      signal,
    );
    return () => {
      // Abandoning a load matters: appending the previous session's pages to
      // this session's transcript would join two transcripts, which is the same
      // defect §8 forbids between two surfaces and for the same reason.
      signal.aborted = true;
    };
  }, [sessionId]);

  // -- the thread the tabs are drawn from (§7.1) -------------------------
  useEffect(() => {
    if (sessionId === null) return;
    let active = true;
    void loadThreadTree(sessionId, fetchThread)
      .then((tree) => {
        if (!active) return;
        setThread({
          sid: sessionId,
          value: { tabs: threadTabs(tree.document), document: tree.document, bounded: tree.bounded },
        });
      })
      .catch((cause: unknown) => {
        if (!active) return;
        // `GET …/thread` is not agent-gated (§2.8), so a refusal here is a real
        // failure and is surfaced rather than rendered as "no thread".
        setError({
          sid: sessionId,
          value: cause instanceof Error ? cause : new Error(String(cause)),
        });
      });
    return () => {
      active = false;
    };
  }, [sessionId]);

  // -- the live suffix (§2.7) --------------------------------------------
  useEffect(() => {
    if (sessionId === null || token === null) return;
    let attached = true;
    const update = (next: (state: LiveState) => LiveState): void => {
      if (!attached) return;
      setLive((prev) => ({
        sid: sessionId,
        value: next(prev.sid === sessionId ? prev.value : CONNECTING),
      }));
    };
    const socket = new StreamSocket(
      { sessionId, token },
      {
        onFrame: (frame) => {
          // §2.7's envelope routes without inspecting payloads. A frame for
          // another session is not this transcript's, and a frame whose
          // `session_id` is null is unrouted — it is not attributed to whatever
          // session this panel happens to be showing.
          if (frame.session_id !== sessionId) return;
          update((state) => receive(state, frame));
        },
        onStatus: (status) => {
          update((state) =>
            status === "live" ? setStatus(state, "live") : disconnected(state, status),
          );
        },
        onResync: () => {
          update((state) => resync(state));
        },
        cursor: () => cursorRef.current,
      },
    );
    socket.open(eventsUrl(window.location));
    return () => {
      // Flag first: `close()` reports `detached`, and a state update after
      // unmount is a warning at best and a leak at worst.
      attached = false;
      socket.close();
    };
  }, [sessionId, token]);

  const clearRunId = useCallback(() => {
    if (sessionId === null) return;
    setLive((prev) => ({
      sid: sessionId,
      value: clearLiveRun(prev.sid === sessionId ? prev.value : CONNECTING),
    }));
  }, [sessionId]);

  const echo = useCallback(
    (text: string) => {
      if (sessionId === null) return;
      setLive((prev) => ({
        sid: sessionId,
        value: appendEcho(prev.sid === sessionId ? prev.value : CONNECTING, text),
      }));
    },
    [sessionId],
  );

  return {
    rows: panelRows(shownHistory.items, shownLive.entries),
    status: shownLive.status,
    history: shownHistory,
    tabs: shownThread.tabs,
    threadState: shownThread.document?.thread_state ?? null,
    threadBounded: shownThread.bounded,
    resyncs: shownLive.resyncs,
    runId: shownLive.runId,
    clearRunId,
    echo,
    terminals: shownLive.terminals,
    error: shownError ?? shownHistory.error,
  };
}
