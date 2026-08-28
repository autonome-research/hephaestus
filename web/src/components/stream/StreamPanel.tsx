// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The STREAM column (INTERFACE.md §4.1, §7, §8).
//
// §4.1 gives the agent "a full-height peer column, collapsible but not hidden by
// default. Giving the agent a column rather than a bottom drawer is the
// 'collaborator, not console' claim cashed out in layout." This is that column's
// contents: the session tabs (§7.1), the stream-state header (§7.4), the page
// counter (§8), and the transcript.
//
// THREE THINGS THIS PANEL SAYS OUT LOUD, because each is a fact a reader would
// otherwise have to infer from silence:
//
// 1. **The stream state.** §7.4's closed vocabulary is on the header, and
//    `resyncing` is visible — "a silent gap in a transcript the user believes is
//    complete is worse than a labelled one."
// 2. **The page count.** §8: "the panel renders progressively and shows a page
//    counter — 'multi-page' is a user-visible fact, not only a test fact." It is
//    the number of pages the server served, counted from responses.
// 3. **`agent_unavailable`.** With no agent runtime, `GET /sessions` refuses
//    `503 agent_unavailable` (`http/app.py::sessions_or_refuse`) and the panel
//    renders that refusal by name. An empty session list would say the project
//    has no sessions, which is a different and false claim.
//
// The composer is not here. §9 puts prompting in Stage 5, and a disabled text
// box with no explanation would be worse than its honest absence — the panel
// states what it can do, and nothing suggests a prompt goes in.

import { useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { WorkspaceError } from "../../api/client";
import { fetchSessions, type SessionRow, type SessionsDocument } from "../../api/sessions";
import { copy } from "../../copy";
import { useWorkspace, workspaceStore } from "../../state/react";
import { useStream } from "../../stream/useStream";
import { SessionTabs } from "./SessionTabs";
import { Transcript } from "./Transcript";
import styles from "./Stream.module.css";

/** Sessions come and go with runs; a short staleness keeps the list honest. */
const SESSIONS_STALE_MS = 5_000;

const EMPTY_SESSIONS: readonly SessionRow[] = [];

export function StreamPanel(): React.JSX.Element {
  const selected = useWorkspace((s) => s.session);
  const sessions = useQuery<SessionsDocument, Error>({
    queryKey: ["sessions"],
    queryFn: fetchSessions,
    staleTime: SESSIONS_STALE_MS,
    // A named refusal is the server's considered answer; retrying an
    // `agent_unavailable` produces the same refusal at the cost of load.
    retry: false,
  });
  // Held stable across renders so the tab-list memo below is not invalidated by
  // a fresh `[]` on every render of an empty list.
  const rows = useMemo(() => sessions.data?.sessions ?? EMPTY_SESSIONS, [sessions.data]);
  const stream = useStream(selected);

  // §4.5 addresses a session as `?s=`. With none in the URL, the first session
  // this server owns is opened — a navigation default, never a fact, and it is
  // written through the same store every other route field goes through.
  const first = rows[0]?.session_id ?? null;
  useEffect(() => {
    if (selected === null && first !== null) workspaceStore.update({ session: first });
  }, [selected, first]);

  // With no thread yet (the walk is in flight, or it failed) the tab list falls
  // back to the flat session list, each row at depth 0 carrying its own
  // `thread_state` from `GET /sessions`. That is the server's own answer, not an
  // inference: `list_sessions` joins the edge table for exactly this field.
  const tabs = useMemo(
    () =>
      stream.tabs.length > 0
        ? stream.tabs
        : rows.map((row) => ({
            session_id: row.session_id,
            parent_session_id: row.parent_session_id,
            kind: null,
            depth: 0,
            thread_state: row.thread_state,
            origin: {},
          })),
    [stream.tabs, rows],
  );

  const unavailable =
    sessions.error instanceof WorkspaceError && sessions.error.reason === "agent_unavailable";

  return (
    <div className={styles["panel"]} data-testid="stream-panel">
      {/* The column's name is already on the shell's own header row; repeating
          it here would put "Agent" twice above one transcript. This row carries
          §7.4's stream state, which is the fact the header exists to show. */}
      <div className={styles["header"]}>
        <span
          className={styles["state"]}
          data-stream-state={stream.status}
          title={copy.stream.stateWhy[stream.status]}
        >
          {copy.stream.state[stream.status]}
        </span>
        {stream.resyncs > 0 ? (
          <span className={styles["resyncCount"]} data-resync-count={stream.resyncs}>
            {stream.resyncs}
          </span>
        ) : null}
      </div>

      {unavailable ? (
        <p className={styles["absent"]} data-refusal-reason="agent_unavailable">
          {copy.stream.noAgent}
        </p>
      ) : sessions.error !== null ? (
        <p
          className={styles["absent"]}
          data-refusal-reason={
            sessions.error instanceof WorkspaceError ? sessions.error.reason : "transport_error"
          }
        >
          {sessions.error.message}
        </p>
      ) : rows.length === 0 && sessions.isFetched ? (
        <p className={styles["absent"]}>{copy.stream.noSessions}</p>
      ) : (
        <SessionTabs
          tabs={tabs}
          sessions={rows}
          selected={selected}
          bounded={stream.threadBounded}
          onSelect={(sessionId) => {
            workspaceStore.update({ session: sessionId });
          }}
        />
      )}

      {selected === null ? (
        <p className={styles["absent"]}>{copy.stream.selectSession}</p>
      ) : (
        <>
          <div className={styles["historyBar"]} data-history-state={stream.history.state}>
            <span data-history-pages={stream.history.pages}>
              {stream.history.state === "loading" && stream.history.pages === 0
                ? copy.stream.historyLoading
                : copy.stream.historyPages(stream.history.pages)}
            </span>
            {stream.history.state === "truncated" ? (
              <span className={styles["note"]}>{copy.stream.historyTruncated}</span>
            ) : null}
            {stream.history.state === "failed" ? (
              <span className={styles["note"]}>{copy.stream.historyFailed}</span>
            ) : null}
          </div>
          <div className={styles["scroll"]}>
            <Transcript rows={stream.rows} />
          </div>
        </>
      )}
    </div>
  );
}
