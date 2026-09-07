// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The Stream header's two exception-only decisions (INTERFACE.md §7.4(a), §8(a),
// both amended 2026-09-01 under §0.2b).
//
// They live here, as pure predicates over the panel's own state, for the reason
// both clauses give a negative half: "renders when required" and "mounts in no
// other state" are two assertions, and a decision spelled inline in a component
// that mounts a query client, a socket and the workspace store can only be
// tested through the one path a fixture happens to reach. `StreamHeader` renders
// what these two functions decide, and nothing decides it twice.
//
// NEITHER FUNCTION DROPS A FACT. §7.4(b) and §8(c) keep `data-stream`,
// `data-history-state` and `data-history-pages` unconditionally on the panel
// root; what these predicates gate is the drawn row, never the attribute.

import type { HistoryProgress } from "./history";
import type { RuntimeFault } from "./runtimeFault";
import type { StreamState } from "./transcript";

/**
 * §7.4(a): the four states that are worth a row. `live` is the fifth word of
 * the closed vocabulary and the one that is never drawn — "a `live` badge is the
 * interface reporting that nothing is wrong, which is the one thing a status
 * line must never spend a row on."
 */
export const EXCEPTIONAL_STREAM_STATES: readonly StreamState[] = [
  "reconnecting",
  "resyncing",
  "historical",
  "detached",
];

/**
 * §7.4(a): the badge mounts iff the socket is in one of the four exceptional
 * states, **or** a runtime fault is known — the fault outranks the socket word
 * and keeps its `error` tone, because a dead sidecar under a `live` socket is
 * the case the badge exists for.
 */
export function showsStreamBadge(status: StreamState, fault: RuntimeFault | null): boolean {
  if (fault !== null) return true;
  return EXCEPTIONAL_STREAM_STATES.includes(status);
}

/**
 * §8(a): the page counter mounts iff the read failed, or there is recorded
 * transcript above the rendered prefix that the reader has not reached.
 *
 * §8(e) makes the second condition a **rendering** fact rather than a derived
 * one, so it is read from the panel's own paging state and from nothing else.
 * This client walks the cursor to `done` and renders every page it fetched, so
 * "not showing the latest page" has exactly one state in this build: the walk
 * that stopped at `MAX_HISTORY_PAGES` (`truncated`) — the pages beyond it are
 * recorded transcript that is not on screen. `complete` is at latest by
 * construction, and `loading` is excluded by (b) by name: "a transcript that is
 * still filling is already visibly filling."
 */
export function showsHistoryBar(history: HistoryProgress): boolean {
  if (history.state === "failed") return true;
  return history.state === "truncated" && history.pages > 1;
}

/**
 * §7.4(e), added 2026-09-05: the state of a session that exists and has no
 * transcript.
 *
 * The panel had no branch for it. `Transcript` maps rows and renders nothing
 * for zero of them, and the only stream empty state was gated on the SESSION
 * LIST being empty — a different claim, and a false one whenever a session is
 * selected. So selecting a session that has never been prompted painted an
 * empty column while `data-history-state="complete"` reported the read had
 * succeeded: §3.3's principle 5 says every state — refusal, absence, no runtime
 * — is a first-class composed state, and this one had no producer of any copy
 * anywhere.
 *
 * SIX EXCLUSIONS, and every one of them is a state that already has its own
 * composed shape which this must not shadow:
 *
 * 1. no session selected — §7A.2's create invitation, or nothing at all;
 * 2. `agent_unavailable` — the composer's §7A.8 refusal owns that cause;
 * 3. a runtime fault — the fault band says the runtime stopped answering;
 * 4. the session listing was refused — the generic §2.4 refusal renders;
 * 5. the history read is not `complete` — `loading` is visibly filling
 *    (§8(b)), `failed` and `truncated` have their own sentences, and claiming
 *    "no turns yet" over a read that did not finish is the lie §4.4 forbids;
 * 6. rows exist — there is a transcript.
 *
 * NO ACTION. §7.1 forbids a create affordance here: the composer directly below
 * is the action, and this session is the one it will prompt.
 */
export interface EmptyTranscript {
  /** §4.5's `?s=` — `null` is "no session addressed", not "an empty one". */
  readonly selected: string | null;
  /** `GET /sessions` refused `agent_unavailable` (§2.4). */
  readonly unavailable: boolean;
  /** The runtime stopped answering (`stream/runtimeFault.ts`). */
  readonly fault: RuntimeFault | null;
  /** `GET /sessions` refused for any other reason. */
  readonly listRefused: boolean;
  /** The paged history walk's own report (§8). */
  readonly history: HistoryProgress;
  /** Rendered transcript rows, live suffix included. */
  readonly rows: number;
}

export function showsEmptyTranscript(state: EmptyTranscript): boolean {
  if (state.selected === null) return false;
  if (state.unavailable) return false;
  if (state.fault !== null) return false;
  if (state.listRefused) return false;
  if (state.history.state !== "complete") return false;
  return state.rows === 0;
}
