// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Quick-edit / delegation threading (INTERFACE.md §7.1, §2.8, binding G4.10).

import { describe, expect, it } from "vitest";
import type { SessionRow, ThreadDocument } from "../../src/api/sessions";
import { loadThreadTree, originPart, sessionForest, threadTabs, type ThreadTab } from "../../src/stream/thread";

const ORCHESTRATOR = "sess-orchestrator";
const PART = "sess-part-bracket";
const CHILD = "sess-quickedit-1";

/** The server's own projection shape (`http/sessions.py::thread_projection`). */
function doc(
  sessionId: string,
  parent: string | null,
  nodes: ThreadDocument["nodes"],
): ThreadDocument {
  return {
    status: "ok",
    session_id: sessionId,
    thread_state: parent !== null || nodes.length > 1 ? "linked" : "unlinked",
    parent_session_id: parent,
    nodes,
  };
}

const TREE: Record<string, ThreadDocument> = {
  [ORCHESTRATOR]: doc(ORCHESTRATOR, null, [
    { session_id: ORCHESTRATOR, parent_session_id: null, kind: null, origin: {}, created_at: null, depth: 0 },
    {
      session_id: PART,
      parent_session_id: ORCHESTRATOR,
      kind: "delegation",
      origin: { delegation_ref: "del:1", parent_run_id: "run-a", child_run_id: "run-b" },
      created_at: 1,
      depth: 1,
    },
    {
      session_id: CHILD,
      parent_session_id: PART,
      kind: "quick_edit",
      origin: { part: "bracket", source_artifact_ref: "art:build:1", selection_id: "sel-3" },
      created_at: 2,
      depth: 2,
    },
  ]),
  [PART]: doc(PART, ORCHESTRATOR, [
    { session_id: PART, parent_session_id: ORCHESTRATOR, kind: "delegation", origin: {}, created_at: 1, depth: 0 },
    {
      session_id: CHILD,
      parent_session_id: PART,
      kind: "quick_edit",
      origin: { part: "bracket" },
      created_at: 2,
      depth: 1,
    },
  ]),
  [CHILD]: doc(CHILD, PART, [
    { session_id: CHILD, parent_session_id: PART, kind: "quick_edit", origin: { part: "bracket" }, created_at: 2, depth: 0 },
  ]),
};

function fetchThread(sessionId: string): Promise<ThreadDocument> {
  const found = TREE[sessionId];
  if (found === undefined) return Promise.reject(new Error(`unknown session ${sessionId}`));
  return Promise.resolve(found);
}

describe("the upward walk (§2.8)", () => {
  it("reaches the orchestrator from a quick-edit child", async () => {
    const tree = await loadThreadTree(CHILD, fetchThread);
    expect(tree.document.session_id).toBe(ORCHESTRATOR);
    expect(tree.hops).toBe(2);
    expect(tree.bounded).toBe(false);
  });

  it("answers in one request for a session that is already a root", async () => {
    const tree = await loadThreadTree(ORCHESTRATOR, fetchThread);
    expect(tree.hops).toBe(0);
  });

  it("terminates on a cycle rather than hanging the panel", async () => {
    const cyclic: Record<string, ThreadDocument> = {
      a: doc("a", "b", [{ session_id: "a", parent_session_id: "b", kind: "quick_edit", origin: {}, created_at: 0, depth: 0 }]),
      b: doc("b", "a", [{ session_id: "b", parent_session_id: "a", kind: "quick_edit", origin: {}, created_at: 0, depth: 0 }]),
    };
    const tree = await loadThreadTree("a", (id) => Promise.resolve(cyclic[id] as ThreadDocument));
    expect(tree.document.session_id).toBe("b");
  });
});

describe("the tabs (§7.1)", () => {
  it("renders the server's three levels at the server's depths", async () => {
    const tree = await loadThreadTree(CHILD, fetchThread);
    const tabs = threadTabs(tree.document);
    expect(tabs.map((tab) => tab.depth)).toEqual([0, 1, 2]);
    expect(tabs.map((tab) => tab.kind)).toEqual([null, "delegation", "quick_edit"]);
  });

  it("marks a session with no recorded edge unlinked, and never guesses a parent", () => {
    const orphan = doc("sess-legacy", null, [
      { session_id: "sess-legacy", parent_session_id: null, kind: null, origin: {}, created_at: null, depth: 0 },
    ]);
    const tabs = threadTabs(orphan);
    expect(tabs).toHaveLength(1);
    expect(tabs[0]?.thread_state).toBe("unlinked");
    expect(tabs[0]?.parent_session_id).toBeNull();
  });

  it("does not stamp the root's unlinked state onto linked children", async () => {
    // The document-level `thread_state` describes the *requested* session. A
    // client that copied it onto every tab would mark a delegated child
    // `unlinked` because its orchestrator happened to be.
    const tree = await loadThreadTree(CHILD, fetchThread);
    const tabs = threadTabs(tree.document);
    expect(tabs.every((tab) => tab.thread_state === "linked")).toBe(true);
  });

  it("reads the part name from a quick-edit edge's origin and nowhere else", () => {
    expect(originPart({ part: "bracket" })).toBe("bracket");
    expect(originPart({})).toBeNull();
    expect(originPart({ part: 7 })).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// B-9 — `sessionForest`: MEMBERSHIP from the listing, SHAPE from the thread
// walk (audit-2026-09-04-broken.md B-9, "Tests to add").
//
// Before the fix, `StreamPanel.tsx` rendered `stream.tabs` whenever the thread
// walk returned anything — which it always does, since `GET …/thread` answers
// at least a one-node tree — so the strip drew exactly ONE connected component
// of the session forest: the one containing the current selection. Creating a
// session (the only way to mint a second root from the browser) left every
// other session off the strip.

function row(
  sessionId: string,
  parent: string | null,
  threadState: SessionRow["thread_state"] = "linked",
): SessionRow {
  return {
    session_id: sessionId,
    profile: "orchestrator",
    part: null,
    parent_session_id: parent,
    thread_state: threadState,
  };
}

function tab(
  sessionId: string,
  parent: string | null,
  depth: number,
  kind: string | null = null,
  threadState: ThreadTab["thread_state"] = "linked",
  origin: Readonly<Record<string, unknown>> = {},
): ThreadTab {
  return {
    session_id: sessionId,
    parent_session_id: parent,
    kind,
    depth,
    thread_state: threadState,
    origin,
    created_at: null,
  };
}

describe("sessionForest — membership from the listing, shape from the thread walk (B-9)", () => {
  it("a listing of three with two threaded and one independent root gives three tabs at depths 0/1/0", () => {
    const rows = [row("sess-o", null), row("sess-p", "sess-o"), row("sess-r", null)];
    // Only `sess-o`/`sess-p` are in the walked thread (the current selection's
    // subtree); `sess-r` is a second root the walk never saw.
    const thread = [tab("sess-o", null, 0), tab("sess-p", "sess-o", 1, "delegation")];
    const forest = sessionForest(rows, thread);
    expect(forest.map((t) => t.session_id)).toEqual(["sess-o", "sess-p", "sess-r"]);
    expect(forest.map((t) => t.depth)).toEqual([0, 1, 0]);
  });

  it("every listed session gets a tab, even when the thread walk saw none of them", () => {
    // The empty thread stands in for "the walk is in flight, or it failed" —
    // §7.1's fallback case. Membership must not depend on the walk succeeding.
    const rows = [row("sess-a", null), row("sess-b", null), row("sess-c", null)];
    const forest = sessionForest(rows, []);
    expect(forest.map((t) => t.session_id).sort()).toEqual(["sess-a", "sess-b", "sess-c"]);
    expect(forest.every((t) => t.depth === 0)).toBe(true);
  });

  it("nests purely from the LISTING's own parent_session_id when the thread walk is empty", () => {
    const rows = [row("sess-o", null), row("sess-p", "sess-o")];
    const forest = sessionForest(rows, []);
    const byId = new Map(forest.map((t) => [t.session_id, t]));
    expect(byId.get("sess-p")?.depth).toBe(1);
    expect(byId.get("sess-o")?.depth).toBe(0);
  });

  it("a listed row whose parent is NOT in the listing gets depth 0 and is never dropped", () => {
    const rows = [row("sess-orphan", "sess-nowhere")];
    const forest = sessionForest(rows, []);
    expect(forest).toHaveLength(1);
    expect(forest[0]?.session_id).toBe("sess-orphan");
    expect(forest[0]?.depth).toBe(0);
  });

  it("a session present in BOTH the listing and the walked thread takes the thread entry's kind and origin", () => {
    const rows = [row("sess-o", null), row("sess-p", "sess-o")];
    const thread = [
      tab("sess-o", null, 0),
      tab("sess-p", "sess-o", 1, "quick_edit", "linked", { part: "bracket" }),
    ];
    const forest = sessionForest(rows, thread);
    const child = forest.find((t) => t.session_id === "sess-p");
    expect(child?.kind).toBe("quick_edit");
    expect(child?.origin).toEqual({ part: "bracket" });
  });

  // NOTE on this case, against the ledger's literal wording. The B-9 "Tests to
  // add" list asks that a merged tab's `thread_state` come from "the listing"
  // rather than the thread entry. The shipped `sessionForest` (see its own doc
  // comment) deliberately does the OPPOSITE and keeps the walked tab's
  // `thread_state` outright, for a reason a listing-wins rule cannot express:
  // `list_sessions` derives `thread_state` per session from whether THAT
  // session has a recorded parent, so an orchestrator root WITH a delegated
  // child would read `unlinked` from the listing alone, even though the thread
  // walk — which sees the child — correctly calls it `linked`
  // (`threadTabs`'s own rule: "a root WITH children is linked"). A listing-wins
  // merge would regress a root with children back to looking unthreaded. This
  // case pins the (correct) shipped behaviour rather than the ledger's literal
  // sentence; see this round's handoff notes for the recommended spec
  // amendment.
  it("keeps the WALKED tab's thread_state for a root with children, even though the listing alone would call it unlinked", () => {
    const rows = [row("sess-o", null, "unlinked"), row("sess-p", "sess-o", "linked")];
    const thread = [tab("sess-o", null, 0, null, "linked"), tab("sess-p", "sess-o", 1, "delegation", "linked")];
    const forest = sessionForest(rows, thread);
    expect(forest.find((t) => t.session_id === "sess-o")?.thread_state).toBe("linked");
  });

  it("roots are emitted in the listing's own order, each followed by its listed descendants breadth-first", () => {
    const rows = [row("sess-r2", null), row("sess-o", null), row("sess-p", "sess-o")];
    const forest = sessionForest(rows, [tab("sess-o", null, 0), tab("sess-p", "sess-o", 1)]);
    expect(forest.map((t) => t.session_id)).toEqual(["sess-r2", "sess-o", "sess-p"]);
  });
});
