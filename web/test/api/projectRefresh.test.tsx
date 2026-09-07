// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// J-web-stream-7: `useProjectRefresh` used to key its subscribe effect on a
// STABLE joined key *and* the id array it was derived from — computed
// precisely so the effect keys on the set's content, sitting right beside the
// value that defeats it. `sessions` and `thread` settle at different times, so
// when the second lands `sessionIds` memoises to a NEW array whose joined form
// is unchanged; the array identity comparison still fails, and the socket is
// torn down and reopened with a byte-identical subscribe frame three
// milliseconds later. The fix reads the array and the selection through refs
// and reduces the dependency list to the stable key and the client.
//
// This is the behavioural companion the ledger asks for: a fake `WebSocket`
// global makes connection CHURN observable (not just the derived id set,
// which `collectSessionIds`'s own unit tests already pin), and the two
// `useQuery` reads are driven directly through `QueryClient.setQueryData` at
// the exact keys the hook reads — the same technique `operator-chrome.test.tsx`
// uses for `ProvidersPanel` — so no real transport is needed.

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it } from "vitest";
import { useProjectRefresh } from "../../src/api/projectRefresh";
import { claimToken, dropToken } from "../../src/api/token";
import { workspaceStore } from "../../src/state/react";
import { DEFAULT_STATE } from "../../src/state/workspace";
import type { SessionsDocument, ThreadDocument } from "../../src/api/sessions";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readonly url: string;
  readonly protocols: readonly string[];

  constructor(url: string, protocols: readonly string[]) {
    this.url = url;
    this.protocols = protocols;
    FakeWebSocket.instances.push(this);
  }

  send(): void {
    /* not exercised: this test is about connection churn, not frames */
  }

  close(): void {
    /* the harness never drives onclose itself, and never needs to: closing
       the real socket on effect cleanup is exercised by unmounting below. */
  }
}

function Harness(): null {
  useProjectRefresh();
  return null;
}

function mount(client: QueryClient): { host: HTMLElement; root: Root } {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => {
    root.render(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>,
    );
  });
  return { host, root };
}

function sessionsDoc(ids: readonly string[]): SessionsDocument {
  return {
    status: "ok",
    profiles: [],
    sessions: ids.map((id) => ({
      session_id: id,
      profile: "part",
      part: "bracket",
      parent_session_id: null,
      thread_state: "linked",
    })),
  };
}

function threadDoc(selected: string, ids: readonly string[]): ThreadDocument {
  return {
    status: "ok",
    session_id: selected,
    thread_state: "linked",
    parent_session_id: null,
    nodes: ids.map((id, index) => ({
      session_id: id,
      parent_session_id: index === 0 ? null : (ids[0] ?? null),
      kind: "part",
      origin: {},
      created_at: null,
      depth: index,
    })),
  };
}

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("useProjectRefresh — one socket per subscribed-set change, none per selection-only change (J-web-stream-7)", () => {
  const realWebSocket = globalThis.WebSocket;

  afterEach(() => {
    workspaceStore.reset(DEFAULT_STATE);
    dropToken();
    FakeWebSocket.instances = [];
    globalThis.WebSocket = realWebSocket;
  });

  it("constructs exactly one socket when sessions settles, none more when thread settles with the same set", async () => {
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    window.history.replaceState(null, "", "/#t=proj-refresh-tok");
    claimToken();
    workspaceStore.update({ part: "bracket", session: "s1" });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { host, root } = mount(client);
    try {
      // `sessions` settles first, alone: {s1}. This must open exactly one
      // socket.
      act(() => {
        client.setQueryData(["sessions"], sessionsDoc(["s1"]));
      });
      await settle();
      expect(FakeWebSocket.instances.length).toBe(1);

      // `thread` settles a tick later with the SAME set (`s1` names itself as
      // the thread's own node, the normal shape of a root with no children
      // yet). `sessionIds` is memoised to a fresh array whose CONTENT is
      // unchanged; this must NOT open a second socket.
      act(() => {
        client.setQueryData(["thread", "s1"], threadDoc("s1", ["s1"]));
      });
      await settle();
      expect(FakeWebSocket.instances.length).toBe(1);
    } finally {
      act(() => {
        root.unmount();
      });
      host.remove();
    }
  });

  it("constructs exactly one more socket when the subscribed set actually changes", async () => {
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    window.history.replaceState(null, "", "/#t=proj-refresh-tok");
    claimToken();
    workspaceStore.update({ part: "bracket", session: "s1" });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { host, root } = mount(client);
    try {
      act(() => {
        client.setQueryData(["sessions"], sessionsDoc(["s1"]));
      });
      await settle();
      expect(FakeWebSocket.instances.length).toBe(1);

      // A delegated child is minted (`s2`): the set genuinely grows, so a
      // second socket carrying the wider subscribe frame IS the correct
      // behaviour.
      act(() => {
        client.setQueryData(["sessions"], sessionsDoc(["s1", "s2"]));
      });
      await settle();
      expect(FakeWebSocket.instances.length).toBe(2);
    } finally {
      act(() => {
        root.unmount();
      });
      host.remove();
    }
  });

  it("constructs no additional socket when only the SELECTED tab changes and the set is unchanged", async () => {
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket;
    window.history.replaceState(null, "", "/#t=proj-refresh-tok");
    claimToken();
    workspaceStore.update({ part: "bracket", session: "s1" });

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(["sessions"], sessionsDoc(["s1", "s2"]));
    const { host, root } = mount(client);
    try {
      await settle();
      expect(FakeWebSocket.instances.length).toBe(1);

      // Switching the open tab from s1 to s2 does not change `collectSessionIds`
      // (both are already listed), so the observer's subscription must not
      // reconnect purely because the operator switched tabs.
      act(() => {
        workspaceStore.update({ session: "s2" });
      });
      await settle();
      expect(FakeWebSocket.instances.length).toBe(1);
    } finally {
      act(() => {
        root.unmount();
      });
      host.remove();
    }
  });
});
