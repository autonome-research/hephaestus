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
// 2. **The page count.** §8: multi-page history is "a user-visible fact, not
//    only a test fact". It is the number of pages the server served, counted
//    from responses.
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
// THE FIRST TWO ARE **DRAWN** ONLY AS EXCEPTIONS (§7.4(a), §8(a), amended
// 2026-09-01). The badge does not mount for a `live` socket with no fault, and
// the counter does not mount for a history whose latest page is the one on
// screen. Neither fact leaves the panel: `data-stream`, `data-history-state`
// and `data-history-pages` are on this panel's ROOT, unconditionally, which is
// what §7.4(b) and §8(c) make the gates read in every state. `StreamHeader`
// owns the row; `stream/streamChrome.ts` owns the two decisions, so each of
// them has exactly one place it is made.
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
// refreshes on the live `terminal` frame instead. A runtime-fault grade that
// means the process is gone is a third turn-settled signal: sidecar death
// produces neither a terminal nor a prompt response, so without it the rail
// stays stale. All three are the same refetch of the same server projection;
// none merges a tool result, and none moves the pin.

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { WorkspaceError } from "../../api/client";
import { attachProjection, type AttachProjection } from "../../api/attach";
import { refreshAfterTurn } from "../../api/refresh";
import { processGone, runtimeFaultOf, type RuntimeFault } from "../../stream/runtimeFault";
import { sessionCannotPrompt } from "../../stream/sessionPromptGate";
import {
  createSession,
  fetchSessions,
  type ProfileCapability,
  type SessionRow,
  type SessionsDocument,
} from "../../api/sessions";
import { useParts } from "../../api/queries";
import { copy } from "../../copy";
import { Button, EmptyState, tabControlId } from "../../system";
import { useWorkspace, workspaceStore } from "../../state/react";
import { sessionEmptyBody, sessionEmptyKind } from "../../stream/sessionEmpty";
import { useStream } from "../../stream/useStream";
import { useFollowScroll } from "../../stream/followScroll";
import { sessionPromptStore } from "../../stream/sessionPrompts";
import { titleForSession } from "../../stream/sessionTitle";
import { Composer, NewSessionAction } from "./Composer";
import { SessionCreateAction, SessionTabs } from "./SessionTabs";
import { StreamHeader } from "./StreamHeader";
import { Transcript } from "./Transcript";
import styles from "./Stream.module.css";

/** Sessions come and go with runs; a short staleness keeps the list honest. */
const SESSIONS_STALE_MS = 5_000;

const EMPTY_SESSIONS: readonly SessionRow[] = [];
const EMPTY_PROFILES: readonly ProfileCapability[] = [];

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
  const [focusNonce, setFocusNonce] = useState(0);

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
            created_at: null,
          })),
    [stream.tabs, rows],
  );

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const { following, jumpToLatest } = useFollowScroll(scrollRef, selected, stream.rows.length);
  const firstPrompts = useSyncExternalStore(
    sessionPromptStore.subscribe,
    sessionPromptStore.getSnapshot,
    sessionPromptStore.getServerSnapshot,
  );
  const sessionTitle = useCallback(
    (sessionId: string) => titleForSession(sessionId, rows, tabs, undefined, firstPrompts[sessionId]),
    [rows, tabs, firstPrompts],
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
  const streamFault = runtimeFaultOf(stream.error);
  const fault: RuntimeFault | null =
    sessionsFault ??
    streamFault ??
    (promptFault.sid === selected ? promptFault.value : null);
  const cannotPrompt = sessionCannotPrompt({
    runtimeFault: fault,
    historyFailed: stream.history.state === "failed",
    streamReason: stream.error instanceof WorkspaceError ? stream.error.reason : null,
  });

  // -- §7A.11, the observer's half ----------------------------------------
  //
  // A live `terminal` for a run on this *project* is owned by
  // `useProjectRefresh` (Shell), not this column: a delegated child writes
  // from a session this tab is not showing, and a collapsed Stream unmounts
  // this panel entirely (#92). The originating tab still refreshes from its
  // prompt response in Composer.
  //
  // Sidecar death produces neither a `terminal` nor a prompt response, so
  // without this path the rail stays stale (#59). A grade that means the
  // process is gone is itself a turn-settled signal: refetch the same keys.
  // A held pin is not written here — `observeCurrent` is already a no-op
  // while held. Selecting a part `create_part` just added is a §4.5
  // amendment, not an advance of `pin_mode === "pinned"`. The project
  // observer repeats this for the collapsed-Stream band.
  const refreshedFault = useRef<RuntimeFault | null>(null);
  useEffect(() => {
    if (fault === null || !processGone(fault)) {
      refreshedFault.current = null;
      return;
    }
    if (refreshedFault.current === fault) return;
    refreshedFault.current = fault;
    refreshAfterTurn(client, part);
  }, [fault, client, part]);

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
          // §7A.2 / #61: the create exists so the operator can talk. Focus
          // the box after the session is addressed; do not wait for a click.
          setFocusNonce((n) => n + 1);
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

  // The worded pair, kept for the two surfaces §7.1(b)(1) leaves it on: the
  // empty-list invitation (§7A.2 — "there is no strip to hang an icon on") and
  // the runtime-fault band, which the clause's own render condition excludes
  // from the `+` by name ("no runtime fault") and which §4.7 keeps loud.
  const createAction = (
    <NewSessionAction profiles={profiles} part={part} pending={creating} onCreate={create} />
  );
  // §7.1(b): beside a drawn tab strip the pair is ONE icon-only `+` at the end
  // of the strip, under exactly the condition the pair rendered under before.
  const stripCreate =
    fault === null && (cannotPrompt || rows.length > 0) ? (
      <SessionCreateAction profiles={profiles} part={part} pending={creating} onCreate={create} />
    ) : null;
  const emptyInvitation = !unavailable && rows.length === 0 && sessions.isFetched;

  return (
    <div
      className={styles["panel"]}
      data-testid="stream-panel"
      // §7.4(b) and §8(c): the socket's own answer, the history read's state and
      // its page count ride on the panel root in EVERY state, because the drawn
      // row is now an exception and a gate cannot read a row that is not there.
      // These three are the durable hooks; nothing about them is conditional.
      data-stream={stream.status}
      data-history-state={stream.history.state}
      data-history-pages={stream.history.pages}
      {...(emptyInvitation ? { "data-stream-empty": "" } : {})}
      {...(cannotPrompt ? { "data-session-cannot-prompt": "" } : {})}
    >
      {/* The column's name is already on the shell's own header row; repeating
          it here would put "Agent" twice above one transcript. This row carries
          §7.4's stream state and §8's page count — and, since 2026-09-01, it
          carries them only when one of them is an exception, so the steady state
          spends no height on a badge saying nothing is wrong. With no session
          there is nothing to report at all. `StreamHeader` returns null when the
          row would be empty; `agent_unavailable` has no history to count. */}
      {selected === null ? null : (
        <StreamHeader
          status={stream.status}
          fault={fault}
          history={unavailable ? null : stream.history}
          resyncs={stream.resyncs}
        />
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
            {/* §7.4(d), amended 2026-09-01: the grade in one sentence, the
                mechanism on `title`. The paragraph is not deleted — a reader
                who wants to know what a restart did to the turn in flight asks
                for it, and the band stops spending four lines saying it to a
                reader who does not. */}
            <span title={copy.stream.runtimeFaultDetail[fault]}>
              {copy.stream.runtimeFaultWhy[fault]}
            </span>
            <span className={styles["note"]} title={copy.stream.runtimeFaultNextDetail}>
              {copy.stream.runtimeFaultNext}
            </span>
            {/* Primary recovery is New session, never Send again. No reconnect
                wizard — no route backs one. */}
            {createAction}
          </div>
        ) : null}

        {!unavailable && sessions.error !== null && sessionsFault === null ? (
          <>
            <EmptyState
              icon="alert"
              title={copy.errors.title}
              body={sessions.error.message}
              data-refusal-reason={refusal !== null ? refusal.reason : "transport_error"}
            />
            {cannotPrompt ? createAction : null}
          </>
        ) : !unavailable && rows.length === 0 && sessions.isFetched ? (
          // §7A.2's entry point. One honest sentence plus the two create
          // actions — a three-paragraph tutorial under the buttons pushed
          // the pinned composer off an 800px stream. When the fault band
          // already carries the pair, do not mount it twice.
          fault !== null ? null : (
            <EmptyState
              icon="info"
              title={copy.stream.noSessionsTitle}
              body={sessionEmptyBody(partCount, part)}
              density="inline"
              data-session-empty={sessionEmptyKind(partCount)}
              action={createAction}
            />
          )
        ) : !unavailable ? (
          <>
            {/* §7A.2 / #70: both create affordances stay reachable after the
                first session exists. Send does not create a session. When
                the current tab cannot prompt, the create is the recovery,
                not only the empty-list invitation. The fault band already
                carries it when a runtime fault is showing.

                §7.1(b), amended: it rides IN the strip as a `+` rather than as
                a band under it, so "New session" and "Ask about <part>" are not
                printed a second time beneath a list whose every row is already
                a session. */}
            <SessionTabs
              tabs={tabs}
              sessions={rows}
              selected={selected}
              bounded={stream.threadBounded}
              panelId="transcript-panel"
              create={stripCreate}
              onSelect={(sessionId) => {
                workspaceStore.update({ session: sessionId });
              }}
            />
          </>
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
            <div
              className={styles["scrollHost"]}
              role="tabpanel"
              id="transcript-panel"
              aria-labelledby={
                selected === null ? undefined : tabControlId("data-session-tab", selected)
              }
            >
              <div className={styles["scroll"]} ref={scrollRef} data-transcript-scroll="">
                <Transcript rows={stream.rows} runtimeFault={fault} />
              </div>
              {following ? null : (
                <Button
                  variant="secondary"
                  className={styles["jumpLatest"]}
                  data-jump-latest=""
                  title={copy.stream.jumpToLatestWhy}
                  onClick={jumpToLatest}
                >
                  {copy.stream.jumpToLatest}
                </Button>
              )}
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
        onForgetLiveRun={stream.clearRunId}
        focusNonce={focusNonce}
        onRuntimeFault={reportFault}
        sessionTitle={sessionTitle}
        onTurnSettled={() => {
          void client.invalidateQueries({ queryKey: ["sessions"] });
        }}
      />
    </div>
  );
}
