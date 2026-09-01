// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The STREAM column (INTERFACE.md §4.1, §7, §7A, §8).
//
// §4.1 gives the agent "a full-height peer column, collapsible but not hidden by
// default. Giving the agent a column rather than a bottom drawer is the
// 'collaborator, not console' claim cashed out in layout." This is that column's
// contents: the session tabs (§7.1), the stream-state header (§7.4), the page
// counter (§8), the transcript — and, as the column's **last child**, the
// composer (§7A.1).
//
// FOUR THINGS THIS PANEL SAYS OUT LOUD, because each is a fact a reader would
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
//    renders that refusal by name — now **with the server's own cause and the
//    path it checked** (§7A.8/§19.25), which used to go to a stderr no browser
//    would read. An empty session list would say the project has no sessions,
//    which is a different and false claim.
// 4. **How a session starts, and how a part comes to exist.** §7A.2: after this
//    section lands, the only way to bring a part into existence from the browser
//    is to type English at an orchestrator agent, which calls `create_part`.
//    "A blank canvas the operator has to guess is filled by talking is the same
//    defect as a composer that is not there."
//
// THE COMPOSER'S CITATION IS STRUCK. This file used to state "§9 puts prompting
// in Stage 5", and §9 does not: it is titled "Stage 5 — editing", its four
// subsections are save/rebuild/conflict/no-lost-write, and the word "prompt"
// occurs in it once, as "merge prompt". §7A.9's table is what actually gates the
// composer, and it gates it here, at Stage 4.
//
// §7A.11 IS IMPLEMENTED HERE AS WELL AS IN THE COMPOSER, and the split is
// deliberate. The originating tab refreshes from its own prompt **response**,
// which §7A.6 makes the authority for turn completion. An *observer* tab has no
// response — the turn was started from a terminal, or from another tab — so it
// refreshes on the live `terminal` frame instead. Both are the same refetch of
// the same server projection; neither merges a tool result, and neither moves
// the pin.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { WorkspaceError } from "../../api/client";
import { attachProjection, type AttachProjection } from "../../api/attach";
import { refreshAfterTurn } from "../../api/refresh";
import { runtimeFaultOf, type RuntimeFault } from "../../stream/runtimeFault";
import {
  createSession,
  fetchSessions,
  type ProfileCapability,
  type SessionRow,
  type SessionsDocument,
} from "../../api/sessions";
import { useParts } from "../../api/queries";
import { copy } from "../../copy";
import { Badge, EmptyState, type BadgeStatus } from "../../system";
import { useWorkspace, workspaceStore } from "../../state/react";
import { sessionEmptyBody, sessionEmptyKind } from "../../stream/sessionEmpty";
import { useStream } from "../../stream/useStream";
import { Composer, NewSessionAction } from "./Composer";
import { SessionTabs } from "./SessionTabs";
import { Transcript } from "./Transcript";
import styles from "./Stream.module.css";

/** Sessions come and go with runs; a short staleness keeps the list honest. */
const SESSIONS_STALE_MS = 5_000;

const EMPTY_SESSIONS: readonly SessionRow[] = [];
const EMPTY_PROFILES: readonly ProfileCapability[] = [];

/**
 * §7.4's five stream states onto §4.7's six-value badge vocabulary.
 *
 * `reconnecting` and `resyncing` are both "the plumbing is working on it" and
 * share the error hue; they are told apart by the WORD, which is the carrier
 * §3.13.2 requires and the one the shipped colour-plus-border pill leaned on
 * least.
 */
const STREAM_STATUS: Readonly<Record<string, BadgeStatus>> = {
  live: "pass",
  reconnecting: "error",
  resyncing: "error",
  historical: "info",
  detached: "not_run",
};

export function StreamPanel(): React.JSX.Element {
  const selected = useWorkspace((s) => s.session);
  const part = useWorkspace((s) => s.part);
  const parts = useParts();
  const partCount = parts.data?.parts.length;
  const client = useQueryClient();
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
  const profiles = useMemo(() => sessions.data?.profiles ?? EMPTY_PROFILES, [sessions.data]);
  const stream = useStream(selected);
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

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

  const refusal = sessions.error instanceof WorkspaceError ? sessions.error : null;
  const unavailable = refusal !== null && refusal.reason === "agent_unavailable";
  // §7A.8/§19.25: the cause rides in §2.4's `data`. `null` covers both "not this
  // refusal" and "this process never attempted an attach", and neither is
  // guessed at — §4.4's rule is that a missing answer says it is missing.
  const attach: AttachProjection | null = unavailable ? attachProjection(refusal.data) : null;

  const activeProfile = rows.find((row) => row.session_id === selected)?.profile ?? null;

  // -- the runtime died under a request (`stream/runtimeFault.ts`) ---------
  //
  // §7.4's five states are all claims about the socket, and the socket outlives
  // a sidecar restart — it reattaches to the fresh child and reports `live`,
  // which is true and is not what the operator needs to know. The fault is a
  // second, independent fact, and it comes from the two places a session
  // request can fail: a read this panel issued (history, thread, the session
  // list) and the prompt the composer issued.
  //
  // TAGGED WITH ITS SESSION, for `useStream`'s reason: a fault belongs to the
  // session it happened in, and clearing it in an effect on tab change is a
  // synchronous setState inside an effect — a cascading render. Tagging makes
  // the reset a *derivation* instead: a fault recorded against another session
  // simply is not this session's fault.
  const [promptFault, setPromptFault] = useState<{
    readonly sid: string | null;
    readonly value: RuntimeFault | null;
  }>({ sid: null, value: null });
  const reportFault = useCallback(
    (value: RuntimeFault | null) => {
      setPromptFault({ sid: selected, value });
    },
    [selected],
  );
  const sessionsFault = runtimeFaultOf(sessions.error);
  const fault: RuntimeFault | null =
    sessionsFault ??
    runtimeFaultOf(stream.error) ??
    (promptFault.sid === selected ? promptFault.value : null);

  // -- §7A.11, the observer's half ----------------------------------------
  //
  // A live `terminal` frame for this session's run means an agent turn on this
  // project just finished. Refetch the enumerated read keys; never merge, never
  // move the pin. The counter is monotone so this fires once per completed run
  // and not again on an unrelated re-render.
  const seenTerminals = useRef(0);
  useEffect(() => {
    if (stream.terminals === seenTerminals.current) return;
    seenTerminals.current = stream.terminals;
    if (stream.terminals === 0) return;
    refreshAfterTurn(client, part);
  }, [stream.terminals, client, part]);

  // §7A.2: `POST /sessions` is reached from exactly two affordances, both
  // explicit — never on focus, never on a first keystroke, never as recovery
  // from a failed prompt. At-least-once is the stated consequence and the UI
  // carries it: a duplicate create is an extra *idle* session, and there is no
  // route that closes one, so none is offered.
  const create = useCallback(
    (profile: "orchestrator" | "part", boundPart: string | null) => {
      setCreating(true);
      setCreateError(null);
      void createSession(profile, boundPart)
        .then((document) => {
          workspaceStore.update({ session: document.session_id });
          void client.invalidateQueries({ queryKey: ["sessions"] });
        })
        .catch((cause: unknown) => {
          setCreateError(cause instanceof Error ? cause.message : copy.errors.title);
        })
        .finally(() => {
          setCreating(false);
        });
    },
    [client],
  );

  return (
    <div className={styles["panel"]} data-testid="stream-panel">
      {/* The column's name is already on the shell's own header row; repeating
          it here would put "Agent" twice above one transcript. This row carries
          §7.4's stream state, which is the fact the header exists to show — and
          it exists only when there is a session to have one. With none, an empty
          32px strip with a rule under it is furniture in a column that needs
          the height, and an `historical` pill over an empty well reads as a
          state the operator has to resolve rather than an invitation to start. */}
      {selected === null ? null : (
        <div className={styles["header"]}>
          {/* §8's page counter, on the header rather than in a bordered row of
              its own. At 1280×800 the well is 420px wide and every full-width
              row with a rule under it is height the transcript does not get;
              "1 page of recorded transcript" did not need one.
              `data-history-state` and `data-history-pages` are unmoved as
              attributes, which is what both gates read. */}
          {!unavailable ? (
            <span className={styles["historyBar"]} data-history-state={stream.history.state}>
              {/* A failed read has no count to report, and "0 pages" beside a
                  stated failure claims a number the load never reached. The
                  attribute still carries the count the panel actually has. */}
              <span data-history-pages={stream.history.pages}>
                {stream.history.state === "failed"
                  ? copy.stream.historyFailedShort
                  : stream.history.state === "loading" && stream.history.pages === 0
                    ? copy.stream.historyLoading
                    : copy.stream.historyPages(stream.history.pages)}
              </span>
            </span>
          ) : null}

          {/* §7.4's five states as a `Badge`, so the state carries an icon and a
              word like every other status. `data-stream-state` is unchanged and
              stays on the styled element, which is the primitive's own (§3.4).

              When a runtime fault is known the badge shows THAT, because it is
              the fact that changes what the operator does next. The attribute
              keeps the socket's own answer — both are true, and a reader
              inspecting the DOM should be able to tell them apart. */}
          <Badge
            status={fault !== null ? "error" : (STREAM_STATUS[stream.status] ?? "info")}
            title={
              fault !== null
                ? copy.stream.runtimeFaultWhy[fault]
                : copy.stream.stateWhy[stream.status]
            }
            data-stream-state={stream.status}
          >
            {fault !== null ? copy.stream.runtimeFault[fault] : copy.stream.state[stream.status]}
          </Badge>
          {stream.resyncs > 0 ? (
            <span className={styles["resyncCount"]} data-resync-count={stream.resyncs}>
              {stream.resyncs}
            </span>
          ) : null}
        </div>
      )}

      {/* §3.3's principle 5: "The agent is a peer surface, and its emptiness
          must look designed… Every state — refusal, absence, 'no runtime
          attached' — is a first-class composed state with a shape, an icon, a
          heading, and where an action exists, a button." A peer column whose
          entire content was two italic 12px sentences at 3.10:1 contradicted the
          layout claim §4.1 makes by giving the agent a column at all.

          `agent_unavailable` no longer renders here: it renders on the composer,
          which is where the operator's next act lives and where §7A.8 puts the
          cause, the path and the one action that can change it. Rendering it
          twice would say the same refusal in two places with two shapes. */}
      <div className={styles["main"]} data-stream-main="">
        {/* The runtime stopped answering, said by name and in place.
            §4.7's second EmptyState rule — "a shared cause is detected once" —
            is why the generic refusal below is suppressed when this band is
            showing the same failure: one cause, one sentence. */}
        {fault !== null ? (
          <div
            className={styles["fault"]}
            data-runtime-fault={fault}
            role="status"
            aria-live="polite"
          >
            <span className={styles["faultTitle"]}>{copy.stream.runtimeFaultTitle}</span>
            <span>{copy.stream.runtimeFaultWhy[fault]}</span>
            <span className={styles["note"]}>{copy.stream.runtimeFaultNext}</span>
          </div>
        ) : null}

        {!unavailable && sessions.error !== null && sessionsFault === null ? (
          <EmptyState
            icon="alert"
            title={copy.errors.title}
            body={sessions.error.message}
            data-refusal-reason={refusal !== null ? refusal.reason : "transport_error"}
          />
        ) : !unavailable && rows.length === 0 && sessions.isFetched ? (
          // §7A.2's entry point. One honest sentence plus the two create
          // actions — a three-paragraph tutorial under the buttons pushed
          // the pinned composer off an 800px stream.
          <EmptyState
            icon="info"
            title={copy.stream.noSessionsTitle}
            body={sessionEmptyBody(partCount, part)}
            density="inline"
            data-session-empty={sessionEmptyKind(partCount)}
            action={
              <NewSessionAction
                profiles={profiles}
                part={part}
                pending={creating}
                onCreate={create}
              />
            }
          />
        ) : !unavailable ? (
          <SessionTabs
            tabs={tabs}
            sessions={rows}
            selected={selected}
            bounded={stream.threadBounded}
            onSelect={(sessionId) => {
              workspaceStore.update({ session: sessionId });
            }}
          />
        ) : null}

        {createError !== null ? (
          <p className={styles["note"]} data-create-error="">
            {createError}
          </p>
        ) : null}

        {selected !== null && !unavailable ? (
          <>
            {/* The two history outcomes that are not a count. `failed` keeps its
                sentence even beside the fault band: one says the recorded
                transcript could not be read, the other says why, and dropping
                the first would leave a transcript that is silently short. */}
            {stream.history.state === "truncated" ? (
              <p className={styles["historyNote"]}>{copy.stream.historyTruncated}</p>
            ) : null}
            {stream.history.state === "failed" ? (
              <p className={styles["historyNote"]}>{copy.stream.historyFailed}</p>
            ) : null}
            <div className={styles["scroll"]}>
              <Transcript rows={stream.rows} />
            </div>
          </>
        ) : null}
      </div>

      {/* §7A.1: the composer is the LAST CHILD of the STREAM column, one per
          session tab, and it renders in every state — including the two where
          it is disabled, because that is exactly where its reason is needed. */}
      <Composer
        sessionId={selected}
        profile={activeProfile}
        attach={attach}
        agentUnavailable={unavailable}
        liveRunId={stream.runId}
        streamLive={stream.status === "live"}
        terminals={stream.terminals}
        onRuntimeFault={reportFault}
        onTurnSettled={() => {
          void client.invalidateQueries({ queryKey: ["sessions"] });
        }}
      />
    </div>
  );
}
