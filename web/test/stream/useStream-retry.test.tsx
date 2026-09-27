// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { HistoryPageDocument } from "../../src/api/sessions";
import * as sessions from "../../src/api/sessions";
import { conversationStore } from "../../src/stream/conversation";
import { useStream } from "../../src/stream/useStream";
import { modelDoc, modelState } from "../fixtures/models";

vi.mock("../../src/api/sessions", async (importOriginal) => {
  const actual = await importOriginal<typeof sessions>();
  return {
    ...actual,
    fetchHistoryPage: vi.fn(),
    fetchThread: vi.fn(),
    fetchSessionModel: vi.fn(),
  };
});

const IDLE_EXECUTION = {
  epoch: "test",
  version: 1,
  run_id: null,
  active_run_id: null,
  admission_available: true,
  terminal: null,
} as const;

beforeAll(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
});

let mounted: { host: HTMLDivElement; root: Root } | null = null;

afterEach(() => {
  if (mounted !== null) {
    act(() => mounted?.root.unmount());
    mounted.host.remove();
    mounted = null;
  }
  conversationStore.reset();
  vi.mocked(sessions.fetchHistoryPage).mockReset();
  vi.mocked(sessions.fetchThread).mockReset();
  vi.mocked(sessions.fetchSessionModel).mockReset();
});

function Probe(): React.JSX.Element {
  const stream = useStream("sess-1");
  return (
    <div data-history-state={stream.history.state} data-history-pages={stream.history.pages}>
      <button type="button" onClick={stream.retryHistory} data-retry-history="">Retry</button>
    </div>
  );
}

function mount(): HTMLElement {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<Probe />));
  mounted = { host, root };
  return host;
}

describe("useStream explicit history retry", () => {
  it("keeps retry authority distinct from initial loading and reruns only the read", async () => {
    let resolveRetry: ((page: HistoryPageDocument) => void) | null = null;
    vi.mocked(sessions.fetchHistoryPage)
      .mockRejectedValueOnce(new Error("history 500"))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRetry = resolve; }));
    vi.mocked(sessions.fetchThread).mockResolvedValue({
      status: "ok",
      session_id: "sess-1",
      thread_state: "linked",
      parent_session_id: null,
      nodes: [],
    });
    vi.mocked(sessions.fetchSessionModel).mockResolvedValue(
      modelDoc("sess-1", modelState, IDLE_EXECUTION),
    );

    const host = mount();
    await act(async () => Promise.resolve());
    expect(host.firstElementChild?.getAttribute("data-history-state")).toBe("failed");
    expect(sessions.fetchHistoryPage).toHaveBeenCalledTimes(1);

    act(() => host.querySelector<HTMLButtonElement>("[data-retry-history]")?.click());
    expect(host.firstElementChild?.getAttribute("data-history-state")).toBe("retrying");
    expect(sessions.fetchHistoryPage).toHaveBeenCalledTimes(2);
    expect(sessions.fetchThread).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveRetry?.({
        status: "ok",
        session_id: "sess-1",
        events: [],
        cursor: null,
        done: true,
        end_cursor: "after-retry",
      });
    });
    expect(host.firstElementChild?.getAttribute("data-history-state")).toBe("complete");
    expect(host.firstElementChild?.getAttribute("data-history-pages")).toBe("1");
  });

  it("returns a failed retry to the explicit failure state", async () => {
    vi.mocked(sessions.fetchHistoryPage)
      .mockRejectedValueOnce(new Error("history 500"))
      .mockRejectedValueOnce(new Error("history still unavailable"));
    vi.mocked(sessions.fetchThread).mockResolvedValue({
      status: "ok",
      session_id: "sess-1",
      thread_state: "linked",
      parent_session_id: null,
      nodes: [],
    });
    vi.mocked(sessions.fetchSessionModel).mockResolvedValue(
      modelDoc("sess-1", modelState, IDLE_EXECUTION),
    );

    const host = mount();
    await act(async () => Promise.resolve());
    expect(host.firstElementChild?.getAttribute("data-history-state")).toBe("failed");
    act(() => host.querySelector<HTMLButtonElement>("[data-retry-history]")?.click());
    expect(host.firstElementChild?.getAttribute("data-history-state")).toBe("retrying");
    await act(async () => Promise.resolve());
    expect(host.firstElementChild?.getAttribute("data-history-state")).toBe("failed");
    expect(sessions.fetchHistoryPage).toHaveBeenCalledTimes(2);
  });
});
