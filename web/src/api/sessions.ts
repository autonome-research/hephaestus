// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The three session reads: the list, the thread, and the paged history
// (INTERFACE.md §2.3, §2.8, §8).
//
// Read types only, transcribed from `http/sessions.py` and
// `agent_bridge/session_edges.py`. Three properties of these routes are
// load-bearing and are stated here so a caller cannot forget them:
//
// * `GET /sessions` lists only the sessions **this runtime owns** — the ones
//   whose `.heph/locks/` leases it holds. A persisted Pi JSONL nobody has opened
//   is not listed, because finding one would mean parsing Pi's format outside
//   the sidecar. §7.1's "attach" affordance lists live sessions, exactly that.
// * `GET /sessions/{id}/history` takes a cursor and **no page size** (§2.8): the
//   cursor is opaque, forwarded and returned unmodified, and page 1 freezes a
//   high-water mark. Rewriting it — or asking for a different size — would break
//   both restart-stability and the frozen mark.
// * `GET /sessions/{id}/thread` returns the subtree rooted at `id` and carries
//   the root's own `parent_session_id` so a client handed a child id can walk
//   *up*. `loadThreadTree` is that walk; the client never infers an edge.
//
// `GET /sessions`, history and prompt refuse `503 agent_unavailable` with no
// agent runtime attached; `…/thread` deliberately does not, because threading is
// durable in `state.db` and readable long after the process that wrote it.

import { apiJson } from "./client";
import type { HistoryEventFrame } from "./events";

/** `agent_bridge/app.py::sessions` + the two fields `list_sessions` joins on. */
export interface SessionRow {
  readonly session_id: string;
  readonly profile: string;
  readonly part: string | null;
  /** From `tp_session_edges`; `null` when this session has no recorded parent. */
  readonly parent_session_id: string | null;
  readonly thread_state: ThreadState;
}

export interface SessionsDocument {
  readonly status: "ok";
  readonly sessions: readonly SessionRow[];
}

/** `SESSION_PROFILES` (`http/sessions.py`), closed at three. */
export const SESSION_PROFILES = ["orchestrator", "part", "quick_edit"] as const;
export type SessionProfile = (typeof SESSION_PROFILES)[number];

/** `THREAD_LINKED` / `THREAD_UNLINKED` — a closed pair (`session_edges.py`). */
export const THREAD_STATES = ["linked", "unlinked"] as const;
export type ThreadState = (typeof THREAD_STATES)[number];

/** `EDGE_KINDS` (`session_edges.py`), closed at two. `null` at a tree root. */
export const EDGE_KINDS = ["quick_edit", "delegation"] as const;
export type EdgeKind = (typeof EDGE_KINDS)[number];

/** One `ThreadNode.as_dict()`. */
export interface ThreadNode {
  readonly session_id: string;
  readonly parent_session_id: string | null;
  readonly kind: string | null;
  readonly origin: Readonly<Record<string, unknown>>;
  readonly created_at: number | null;
  readonly depth: number;
}

/** `GET /sessions/{id}/thread` — `thread_projection`. */
export interface ThreadDocument {
  readonly status: "ok";
  readonly session_id: string;
  readonly thread_state: ThreadState;
  readonly parent_session_id: string | null;
  readonly nodes: readonly ThreadNode[];
}

/**
 * `GET /sessions/{id}/history` — `history.page` passthrough.
 *
 * `cursor` is `null` exactly when `done` is true; both are the sidecar's own
 * fields (`agent/src/session/history.ts::HistoryPage`) and neither is rewritten
 * anywhere between there and here.
 */
export interface HistoryPageDocument {
  readonly status: "ok";
  readonly session_id: string;
  readonly events: readonly HistoryEventFrame[];
  readonly cursor: string | null;
  readonly done: boolean;
}

/** `MAX_THREAD_DEPTH` (`session_edges.py`), mirrored so the upward walk is bounded. */
export const MAX_THREAD_DEPTH = 32;

export function sessionPath(sessionId: string, suffix: string): string {
  return `/sessions/${encodeURIComponent(sessionId)}${suffix}`;
}

export function fetchSessions(): Promise<SessionsDocument> {
  return apiJson<SessionsDocument>("/sessions");
}

export function fetchThread(sessionId: string): Promise<ThreadDocument> {
  return apiJson<ThreadDocument>(sessionPath(sessionId, "/thread"));
}

/**
 * One history page. `cursor` is forwarded **verbatim** — never decoded, never
 * re-encoded, and never accompanied by a page size (§2.8).
 *
 * `encodeURIComponent` is percent-encoding for the query string, not a rewrite:
 * a base64url cursor (`[A-Za-z0-9_-]`) passes through it unchanged byte for
 * byte, and the escape exists so a cursor shape that ever gained another
 * character still arrives as the server minted it rather than as URL syntax.
 */
export function fetchHistoryPage(
  sessionId: string,
  cursor: string | null,
): Promise<HistoryPageDocument> {
  const query = cursor === null ? "" : `?cursor=${encodeURIComponent(cursor)}`;
  return apiJson<HistoryPageDocument>(sessionPath(sessionId, `/history${query}`));
}
