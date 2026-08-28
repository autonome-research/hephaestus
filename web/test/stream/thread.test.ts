// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Quick-edit / delegation threading (INTERFACE.md §7.1, §2.8, binding G4.10).

import { describe, expect, it } from "vitest";
import type { ThreadDocument } from "../../src/api/sessions";
import { loadThreadTree, originPart, threadTabs } from "../../src/stream/thread";

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
