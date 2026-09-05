// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Session threading (INTERFACE.md §7.1, §2.8, binding G4.10).
//
// §7.1: "One tab per attached session, nested: an orchestrator, its delegated
// part sessions, and a part session's quick-edit children form a three-level
// tree rendered as an indented tab list with `data-thread-depth`. **The edge
// source is `GET /sessions/{id}/thread` — never inference.**"
//
// So nothing in this file guesses at a parent. It walks edges the server
// recorded in `tp_session_edges` and stops.
//
// THE UPWARD WALK, and why the client owns it. `GET /sessions/{id}/thread`
// returns the subtree rooted at `id` and carries the root's own
// `parent_session_id` — `SessionEdgeStore.thread`'s docstring says it does so
// "so a client handed a child id can walk *up* as well as down". A quick-edit
// child opened from a URL is exactly that client. `loadThreadTree` follows
// `parent_session_id` to the topmost recorded ancestor and returns *that*
// session's tree, which is the one §7.1 renders. It is bounded by the server's
// own `MAX_THREAD_DEPTH`, and a cycle — impossible through well-formed writes,
// possible in a hand-edited table — terminates on a visited set rather than
// hanging the panel.
//
// THE HONESTY STATE. §2.8: "an edge created before this table exists cannot be
// recovered. Pre-existing transcripts reopen flat, and the UI says so
// (`data-thread-state='unlinked'`) rather than guessing a parent." `unlinked` is
// therefore rendered as a *stated* condition on the tab, not as the absence of
// an indent — an unindented tab and an unrecoverable parent look identical, and
// only one of them is a fact about the project.

import {
  MAX_THREAD_DEPTH,
  type SessionRow,
  type ThreadDocument,
  type ThreadNode,
  type ThreadState,
} from "../api/sessions";

export type ThreadFetcher = (sessionId: string) => Promise<ThreadDocument>;

export interface ThreadTree {
  /** The tree rooted at the topmost recorded ancestor. */
  readonly document: ThreadDocument;
  /** How many parents were followed to reach it. Zero for a root. */
  readonly hops: number;
  /** True when the walk stopped on the depth bound rather than on a root. */
  readonly bounded: boolean;
}

/**
 * Walk up to the topmost recorded ancestor, then return its subtree.
 *
 * A session with no edge is its own root and answers in one request: the server
 * returns a one-node tree with `thread_state: "unlinked"`, which is the honest
 * answer for a transcript that predates the edge table — not an error, and not
 * an empty list.
 */
export async function loadThreadTree(
  sessionId: string,
  fetchThread: ThreadFetcher,
): Promise<ThreadTree> {
  let document = await fetchThread(sessionId);
  const seen = new Set<string>([sessionId]);
  let hops = 0;
  while (document.parent_session_id !== null && hops < MAX_THREAD_DEPTH) {
    const parent = document.parent_session_id;
    if (seen.has(parent)) break;
    seen.add(parent);
    document = await fetchThread(parent);
    hops += 1;
  }
  return {
    document,
    hops,
    bounded: document.parent_session_id !== null && hops >= MAX_THREAD_DEPTH,
  };
}

/** One rendered tab: a thread node plus what the panel needs beside it. */
export interface ThreadTab {
  readonly session_id: string;
  readonly parent_session_id: string | null;
  /** `quick_edit` / `delegation` from `EDGE_KINDS`; `null` at the tree root. */
  readonly kind: string | null;
  readonly depth: number;
  readonly thread_state: ThreadState;
  readonly origin: Readonly<Record<string, unknown>>;
  /** From the edge row; `null` at a list fallback that has no thread walk. */
  readonly created_at?: number | null;
}

/**
 * The tab list, in the server's breadth-first order.
 *
 * `thread_state` is per node, not per document: the tree's root is `unlinked`
 * only when it has neither a parent nor children, and every node below it is
 * linked by the very edge that put it there. The document-level
 * `thread_state` describes the *requested* session, so a client that stamped it
 * on every tab would mark a delegated child `unlinked` because its orchestrator
 * happened to be one.
 */
export function threadTabs(document: ThreadDocument): readonly ThreadTab[] {
  return document.nodes.map((node: ThreadNode): ThreadTab => {
    const linked = node.parent_session_id !== null || document.nodes.length > 1;
    return {
      session_id: node.session_id,
      parent_session_id: node.parent_session_id,
      kind: node.kind,
      depth: node.depth,
      thread_state: linked ? "linked" : "unlinked",
      origin: node.origin,
      created_at: node.created_at,
    };
  });
}

/**
 * The strip's tab list: MEMBERSHIP from the sessions listing, SHAPE from the
 * thread walk (§7.1, corrected 2026-09-04).
 *
 * THE SPLIT IS THE FIX, and the defect it retires is worth stating. The panel
 * used to render `threadTabs(selected)` and fall back to the flat listing only
 * when that walk returned nothing. But `GET /sessions/{id}/thread` always
 * returns at least a one-node tree, so the fallback was dead code in every real
 * state and the strip drew exactly ONE connected component of the session
 * forest — the one holding the selection. With two seeded sessions in one thread
 * and a third created from the strip, the create left a single tab: the new
 * session, alone, while `GET /sessions` returned three rows. Both pre-existing
 * sessions vanished because they are a different component.
 *
 * So: **the listing decides which sessions exist** — §7.1's "one tab per
 * attached session", every one of them, in every state — and the thread decides
 * what an edge is: kind, origin, creation time. A session that is listed but is
 * not in the selected subtree renders as a root whose edges are simply unknown,
 * which is a fact the tab states with `data-thread-state`, rather than as an
 * absence.
 *
 * NOTHING HERE GUESSES A PARENT, which is §7.1's other half. Depth is READ:
 * `GET /sessions` carries `parent_session_id` from the same edge join
 * (`http/sessions.py::list_sessions`), so a row outside the walk still knows who
 * its parent is. A parent id that is not itself listed is treated as ABSENT —
 * the tab is a root at depth 0 — because an indent under a tab that is not on
 * screen is a claim about a session the strip is not showing.
 *
 * Depth is recomputed for every tab by counting LISTED ancestors rather than
 * copied off the thread node. When the whole thread is listed the two agree
 * exactly (that is the common case and the e2e pins it); when they disagree, the
 * walk stopped on `MAX_THREAD_DEPTH` and the thread's own depth is relative to a
 * root the listing can see past. One rule, so an indent always means "this many
 * of my ancestors are tabs above me".
 *
 * The union is not a new idea in this client: `api/projectRefresh.ts` merges a
 * listing with a subscription document the same way.
 */
export function sessionForest(
  rows: readonly SessionRow[],
  thread: readonly ThreadTab[],
): readonly ThreadTab[] {
  const walked = new Map(thread.map((tab) => [tab.session_id, tab]));
  const listed = new Set(rows.map((row) => row.session_id));

  // One record per listed session, in the server's listing order. A thread entry
  // wins outright where there is one: it carries the edge's kind, origin and
  // creation time, and its `thread_state` is the per-node answer `threadTabs`
  // derives from the tree — a root WITH children is linked, which the listing's
  // own field cannot say (`list_sessions` reads only the edge naming this
  // session's parent, so every orchestrator is `unlinked` there).
  const merged: ThreadTab[] = rows.map((row) => {
    const tab = walked.get(row.session_id);
    if (tab !== undefined) return tab;
    return {
      session_id: row.session_id,
      parent_session_id: row.parent_session_id,
      kind: null,
      depth: 0,
      thread_state: row.thread_state,
      origin: {},
      created_at: null,
    };
  });

  const parentOf = (tab: ThreadTab): string | null => {
    const parent = tab.parent_session_id;
    return parent !== null && parent !== tab.session_id && listed.has(parent) ? parent : null;
  };

  const children = new Map<string, ThreadTab[]>();
  const roots: ThreadTab[] = [];
  for (const tab of merged) {
    const parent = parentOf(tab);
    if (parent === null) {
      roots.push(tab);
      continue;
    }
    const siblings = children.get(parent);
    if (siblings === undefined) children.set(parent, [tab]);
    else siblings.push(tab);
  }

  // Breadth-first per root, roots in the listing's order — the same shape
  // `thread_projection` serves, so a thread that is wholly listed comes back in
  // the order the server put it in.
  const out: ThreadTab[] = [];
  const emitted = new Set<string>();
  for (const root of roots) {
    let level: readonly ThreadTab[] = [root];
    let depth = 0;
    while (level.length > 0) {
      const next: ThreadTab[] = [];
      for (const tab of level) {
        if (emitted.has(tab.session_id)) continue;
        emitted.add(tab.session_id);
        out.push(depth === tab.depth ? tab : { ...tab, depth });
        next.push(...(children.get(tab.session_id) ?? []));
      }
      level = next;
      depth = Math.min(depth + 1, MAX_THREAD_DEPTH);
    }
  }

  // A listed session reachable from no root is only possible through a parent
  // cycle, which no well-formed write can make and a hand-edited table can. It
  // is still a session this runtime owns, so it renders — flat, and never
  // dropped, which is the property this whole function exists to hold.
  for (const tab of merged) {
    if (!emitted.has(tab.session_id)) out.push(tab.depth === 0 ? tab : { ...tab, depth: 0 });
  }
  return out;
}

/**
 * §7.1's part label for a quick-edit tab, read from the edge's `origin`.
 *
 * `origin` for a `quick_edit` edge is
 * `{part, source_artifact_ref, selection_id, provenance, crop_artifact_ref}`
 * (§2.8). Only `part` is read here; the rest is the quick-edit popover's work
 * and reading it into a tab label would be a panel claiming provenance it is not
 * showing.
 */
export function originPart(origin: Readonly<Record<string, unknown>>): string | null {
  const part = origin["part"];
  return typeof part === "string" && part !== "" ? part : null;
}
