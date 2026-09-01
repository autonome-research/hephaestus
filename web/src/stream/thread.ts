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
