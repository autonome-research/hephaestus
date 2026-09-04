// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The live stream's state, as a pure reducer (INTERFACE.md §2.7, §7.4).
//
// WHY THIS IS A REDUCER AND NOT A HOOK. Everything §2.7 says about a resync is a
// claim about *what the panel shows after a socket drops*, and that claim has to
// be testable without a browser, a server, or a socket. The transport lives in
// `socket.ts` and does nothing but turn WebSocket events into the actions below.
//
// THE HONESTY REQUIREMENT, stated as the invariant this file keeps:
//
//   §2.7: on overflow the server closes the socket `4409 resync_required` and
//   drops the client; it never cancels the run. The client reconnects with
//   `{"resume": {...}}` and "replays whatever the live buffer still holds", and
//   "renders anything the buffer dropped as a **labelled break** (§7.4's
//   `resyncing` state). The break is never healed from history."
//
// So a resync **always** inserts a break row. It is never removed, never merged
// away, and the events that arrive after it are never spliced onto the events
// before it as though nothing happened. What the break says varies with what the
// client can honestly determine (`ResyncOutcome`), and "I cannot tell" is one of
// the four answers rather than a rounding to the reassuring one.
//
// THE SERVER SENDS NO GAP SIGNAL, and inventing one would widen a closed
// vocabulary. `http/events_ws.py::_replay` computes contiguity — the live
// buffer's `replay` returns it — and then discards it, because emitting it would
// mean a frame outside §2.7's ten kinds. The client therefore derives the same
// fact from the only evidence it has: `seq` is run-monotonic
// (`active.nextSeq()`), so the first post-resume event for the cursor's run is
// contiguous exactly when its `seq` is the cursor's `seq + 1`.

import { liveEventId, type EventFrame } from "../api/events";
import {
  liveItem,
  type LiveEntry,
  type ResyncBreak,
  type ResyncOutcome,
  type StreamState,
  type TranscriptItem,
} from "./transcript";

/** The `entry: "echo"` member of `LiveEntry` — this module's own writes to it. */
type EchoEntry = Extract<LiveEntry, { readonly entry: "echo" }>;

/**
 * §7A.5's closed `data-echo-state` vocabulary — THIS MODULE'S OWN COPY.
 *
 * `transcript.ts` carries the same three-member set on `LiveEntry`'s echo
 * variant and says why a second copy is correct rather than sloppy: "`live.ts`
 * holds the SENDER's copy of this set … The two cannot drift silently:
 * `liveRows` assigns one to the other, so a member added on either side and
 * not the other fails to compile." This is that copy.
 *
 * `unknown` (a POST that never came back) is a real member, but nothing in
 * this module transitions an echo into it: the composer's own
 * `data-send-state="unknown"` already carries that fact (`Composer.tsx`), and
 * §7A.5 gives the echo itself no second, redundant path to the same word.
 */
export const ECHO_STATES = ["sent", "unknown", "refused"] as const;
export type EchoState = (typeof ECHO_STATES)[number];

/** The close code §2.7 assigns to an overflowed observer, with its reason. */
export const RESYNC_CLOSE_CODE = 4409;
export const RESYNC_CLOSE_REASON = "resync_required";

export interface LiveCursor {
  readonly run_id: string;
  readonly seq: number;
}

/**
 * How many live identities are remembered for the duplicate check.
 *
 * The server's `PerClientQueue` bound is 1024, and the live buffer's replay can
 * never hand back more than the buffer holds, so a window of that size covers
 * every overlap a resume can produce. It is bounded because a session can run
 * for hours and a growing set of every identity ever seen is a leak.
 */
export const LIVE_DEDUPE_WINDOW = 1024;

export interface LiveState {
  readonly status: StreamState;
  readonly entries: readonly LiveEntry[];
  /** The last live identity seen, for `{"resume": {"after": …}}`. */
  readonly cursor: LiveCursor | null;
  /** How many times this panel has been dropped and resumed. Rendered. */
  readonly resyncs: number;
  /**
   * The run that is live *now* (§7A.5).
   *
   * **The composer's only source of its own run id.** `run_prompt` blocks for
   * the whole turn, so its response arrives *after* the run is over and cannot
   * be the source of a mid-run cancel target; the id therefore comes from the
   * first `/events` frame whose envelope `session_id` matches the tab —
   * precisely the field §2.7 added the envelope for. It is **cleared** on the
   * `terminal` frame that ends that run, and on submit (see `clearLiveRun`), so
   * a finished id is never offered as a cancel target. Distinct from `cursor`,
   * which deliberately stops advancing on a `terminal` (its `seq = 2**62` is
   * past `Number.MAX_SAFE_INTEGER`).
   */
  readonly runId: string | null;
  /**
   * How many live `terminal` frames this session has seen (§7A.11).
   *
   * A monotone counter rather than a flag, so the read-refresh effect fires
   * once per completed run and never re-fires on an unrelated re-render. The
   * client reads §7A.11's boundary off this: "on a `terminal` frame for a run
   * on this project … the client invalidates" the enumerated read keys.
   */
  readonly terminals: number;
  /** Recently seen `<run_id>#<seq>` identities, newest last. */
  readonly seen: readonly string[];
  /**
   * §7.4 (amended 2026-09-03): did THIS mount ever receive a live frame whose
   * `seq > 0` before it had received any live frame at all?
   *
   * A live run's `seq` is run-monotonic and starts at 0
   * (`agent/src/main.ts:509`), so a `seq > 0` first frame is proof that frames
   * of that run exist which this mount never received — it attached while the
   * run was already in progress. DECIDED ONCE, FROM THE FIRST FRAME ONLY:
   * once `true` nothing clears it (not a later run starting cleanly, not a
   * resync) — the fact this field records is about *this mount's history*,
   * not about the run that happens to be live right now. `transcript.ts`'s
   * `seamKind` derives the same fact independently from the held
   * `LiveEntry[]` for the seam row itself; this field is the same held fact
   * exposed as a plain boolean for any other consumer (`useStream.ts`'s
   * `StreamView.midRunAttach`) without re-walking the entry list.
   */
  readonly midRunAttach: boolean;
}

export function emptyLive(status: StreamState = "historical"): LiveState {
  return {
    status,
    entries: [],
    cursor: null,
    resyncs: 0,
    seen: [],
    runId: null,
    terminals: 0,
    midRunAttach: false,
  };
}

/**
 * One frame arrived.
 *
 * Three things happen beyond appending, and two of them were found by driving a
 * real `heph serve --web` socket rather than by reading the spec.
 *
 * **1. A replayed duplicate is dropped.** `LiveBuffer.replay` looks the client's
 * cursor up in the ring and, when it is *not* there, returns everything the ring
 * holds for that session — the honest suffix, but a suffix that overlaps what
 * this panel already rendered. Deduping on `(run_id, seq)` is sound *here*
 * because that is the live namespace's own identity (§2.8); what §2.7 forbids is
 * deduping **across** the two namespaces, where the same logical event has two
 * disjoint identities and a dedupe would never match. This one always matches,
 * or the events are genuinely different.
 *
 * **2. The cursor advances only on a seq JavaScript can carry back.** A
 * `terminal` is minted with `seq = 2**62` so terminals sort last
 * (`agent_bridge/events.py`), and `2**62` is far past `Number.MAX_SAFE_INTEGER`:
 * a browser's `JSON.parse` rounds it, so echoing it in `{"resume": {"after":
 * …}}` would send the server a number it never minted, the lookup would miss,
 * and the panel would report a **gap that did not happen**. A terminal is the
 * last event of its run, so holding the cursor at the last ordinary event costs
 * nothing and keeps every resume answerable. Verified against a live socket:
 * the terminal arrives as `4611686018427388000`, not `4611686018427387904`.
 *
 * **3. A pending break is decided.** Contiguous when the frame is the cursor's
 * successor, a gap when it is past it. A frame from another run leaves the break
 * pending, because it says nothing about the run whose continuity is in
 * question.
 */
export function receive(state: LiveState, frame: EventFrame): LiveState {
  const identity = liveEventId(frame.run_id, frame.seq);
  if (state.seen.includes(identity)) return state;
  // §7.4: mirrors `transcript.ts::seamKind`'s own walk exactly, so the two
  // derivations of "the same held fact" can never disagree. `seamKind` scans
  // `entries` for the first `echo` or `event` (skipping `break`s) and decides
  // right there — an `echo` seen first means "end" unconditionally (C1's
  // license: a Send this tab performed starts the run it is about to watch,
  // whatever that run's first frame's `seq` turns out to be), an `event` seen
  // first decides on its `seq`. So the decision here is frozen the moment
  // `entries` already holds an `echo` OR an `event` — not merely an `event` —
  // and, once frozen, a later frame never revisits it (see the field's own
  // doc: not a later run starting cleanly, not a resync).
  const decided = state.entries.some((entry) => entry.entry === "echo" || entry.entry === "event");
  const midRunAttach = state.midRunAttach || (!decided && frame.seq > 0);
  const item = liveItem(frame);
  const entries = decidePending(state.entries, item);
  const seen = [...state.seen, identity];
  return {
    // A frame in hand IS the live state; nothing else needs to say so.
    status: "live",
    entries: [...entries, { entry: "event", item }],
    cursor: Number.isSafeInteger(frame.seq)
      ? { run_id: frame.run_id, seq: frame.seq }
      : state.cursor,
    // Set from a live frame; cleared on `terminal` so the id the composer
    // holds is only ever a run that is live *now*. Unlike `cursor`, which must
    // not carry a seq the browser rounded, this is an identity the composer
    // renders, never a value echoed back to the server.
    runId: frame.kind === "terminal" ? null : frame.run_id,
    terminals: state.terminals + (frame.kind === "terminal" ? 1 : 0),
    resyncs: state.resyncs,
    seen: seen.length > LIVE_DEDUPE_WINDOW ? seen.slice(seen.length - LIVE_DEDUPE_WINDOW) : seen,
    midRunAttach,
  };
}

function decidePending(
  entries: readonly LiveEntry[],
  item: TranscriptItem,
): readonly LiveEntry[] {
  const index = lastPendingBreak(entries);
  if (index === -1) return entries;
  const entry = entries[index];
  if (entry === undefined || entry.entry !== "break") return entries;
  const after = entry.resync.after;
  if (after === null) {
    // Nothing was ever seen before the drop, so there is no cursor to be
    // contiguous *with*. The break stays, and says exactly that.
    return replace(entries, index, { ...entry.resync, outcome: "unknown" });
  }
  if (item.runId !== after.run_id) return entries;
  const outcome: ResyncOutcome = item.seq === after.seq + 1 ? "contiguous" : "gap";
  return replace(entries, index, { ...entry.resync, outcome });
}

function replace(
  entries: readonly LiveEntry[],
  index: number,
  resync: ResyncBreak,
): readonly LiveEntry[] {
  const copy = [...entries];
  copy[index] = { entry: "break", resync };
  return copy;
}

function lastPendingBreak(entries: readonly LiveEntry[]): number {
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    const entry = entries[i];
    if (entry === undefined) continue;
    // A C2 echo between the break and the next frame is not evidence about
    // the stream's continuity — it is the operator typing while the socket
    // reattaches — so the walk looks past it to the break awaiting a verdict.
    if (entry.entry === "echo") continue;
    if (entry.entry === "event") return -1;
    if (entry.resync.outcome === "pending") return i;
    return -1;
  }
  return -1;
}

/**
 * §7A.5 (C1): the originating tab's Send appends the local-prompt echo entry —
 * the sent text verbatim, at the live suffix's tail.
 *
 * Appended, never inserted, and never removed by anything in this module: a
 * lost POST leaves it standing (the words were sent into uncertainty, and
 * hiding them would un-say something the operator said — the composer's
 * `data-send-state="unknown"` renders beside it). A second Send appends a
 * second echo. Nothing here is called by history load, a resync, or an
 * observer tab — only the composer's own submit reaches it, which is what
 * makes the echo a presentation row minted from held state (§7.3's C2).
 */
export function appendEcho(state: LiveState, text: string): LiveState {
  let echoes = 0;
  for (const entry of state.entries) if (entry.entry === "echo") echoes += 1;
  const entry: EchoEntry = {
    entry: "echo",
    key: `echo:${String(echoes)}`,
    text,
    state: "sent",
    refusedReason: null,
  };
  return { ...state, entries: [...state.entries, entry] };
}

/**
 * §7A.5: a NAMED refusal to `POST .../prompt` (`run_in_flight`,
 * `agent_unavailable`, or any other closed reason the route names) marks the
 * most recently sent echo `refused`, carrying the server's reason verbatim.
 *
 * The text is never touched — C2's never-removed rule is untouched by this
 * function; only the presentation state changes. Marks the LAST echo entry
 * rather than one addressed by key: the composer disables Send for the whole
 * duration of a pending POST (`post.phase === "sending"`, `Composer.tsx`), so
 * at most one echo is ever unsettled at a time and "the last one" is
 * unambiguous. Idempotent against a second report for the same echo.
 *
 * Deliberately NOT called for §7A.5's OTHER named outcome, `unknown` (a POST
 * that never came back at all) — see `ECHO_STATES`'s doc comment for why.
 */
export function refuseEcho(state: LiveState, reason: string): LiveState {
  const index = lastEchoIndex(state.entries);
  if (index === -1) return state;
  const entry = state.entries[index];
  if (entry === undefined || entry.entry !== "echo" || entry.state === "refused") return state;
  const updated: EchoEntry = { ...entry, state: "refused", refusedReason: reason };
  const entries = [...state.entries];
  entries[index] = updated;
  return { ...state, entries };
}

function lastEchoIndex(entries: readonly LiveEntry[]): number {
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    if (entries[i]?.entry === "echo") return i;
  }
  return -1;
}

/**
 * The socket was closed `4409 resync_required`.
 *
 * The break goes in **now**, while the panel is still showing the events before
 * it, rather than after the replay decides what was lost. A panel that waited
 * would show an unbroken transcript during the window when it is provably
 * missing events — which is §7.4's "silent gap in a transcript the user believes
 * is complete", the thing that section calls worse than a labelled one.
 */
export function resync(state: LiveState): LiveState {
  const count = state.resyncs + 1;
  const resyncBreak: ResyncBreak = {
    key: `resync:${String(count)}`,
    outcome: "pending",
    after: state.cursor,
  };
  return {
    ...state,
    status: "resyncing",
    entries: [...state.entries, { entry: "break", resync: resyncBreak }],
    resyncs: count,
  };
}

/**
 * The socket closed for a reason that is **not** an overflow.
 *
 * No break is inserted: a network drop or a server restart did not overflow a
 * queue, so claiming the transcript lost events would be as dishonest in the
 * other direction. The header state carries it instead.
 */
export function disconnected(state: LiveState, next: StreamState): LiveState {
  return { ...state, status: next };
}

/** A status transition with no other effect (`connecting`, `open`, `detached`). */
export function setStatus(state: LiveState, next: StreamState): LiveState {
  return { ...state, status: next };
}

/**
 * Forget the live run id (§7A.5).
 *
 * Called on submit so a second turn cannot offer Cancel against the previous
 * run during the window before the first frame of the new one arrives. The
 * next matching frame sets `runId` again.
 */
export function clearLiveRun(state: LiveState): LiveState {
  if (state.runId === null) return state;
  return { ...state, runId: null };
}

/**
 * The resume frame for the current cursor, or `null` when there is nothing to
 * resume from — in which case the socket subscribes and the transcript simply
 * begins where it begins.
 */
export function resumeFrame(
  state: LiveState,
  sessionId: string,
): { readonly resume: { readonly session_id: string; readonly after: LiveCursor } } | null {
  if (state.cursor === null) return null;
  return { resume: { session_id: sessionId, after: state.cursor } };
}
