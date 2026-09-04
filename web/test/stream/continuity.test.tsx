// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Well continuity after remount (INTERFACE.md §7.3, §8): session selection
// and recorded operator turns come back from history, not from the page store.
// The run-ended hedge does not enter the document.

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Transcript } from "../../src/components/stream/Transcript";
import { Composer } from "../../src/components/stream/Composer";
import { copy } from "../../src/copy";
import { DEFAULT_STATE } from "../../src/state/workspace";
import { workspaceStore, useWorkspace } from "../../src/state/react";
import {
  historicalItem,
  historicalRows,
  panelRows,
  type PanelRow,
} from "../../src/stream/transcript";
import { useStream } from "../../src/stream/useStream";
import {
  createSession,
  fetchHistoryPage,
  fetchThread,
  sendPrompt,
  type CreatedSessionDocument,
  type PromptDocument,
  type ThreadDocument,
} from "../../src/api/sessions";
import type * as SessionsModule from "../../src/api/sessions";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// This file's own stub of `api/sessions` — separate from `composer.test.tsx`'s,
// vitest module mocks are per test FILE. Needed only by the harness describe
// block near the bottom; every other test here calls the real pure functions.
vi.mock("../../src/api/sessions", async (importOriginal) => {
  const actual = await importOriginal<typeof SessionsModule>();
  return {
    ...actual,
    createSession: vi.fn(),
    sendPrompt: vi.fn(),
    fetchHistoryPage: vi.fn(),
    fetchThread: vi.fn(),
  };
});

const HEDGE = "This reopened transcript doesn't show how the run ended.";

function textFrame(seq: number, text: string) {
  return {
    run_id: "sess-1",
    seq,
    kind: "text_delta",
    payload: { text },
  };
}

function mountTranscript(rows: ReturnType<typeof historicalRows>): HTMLElement {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => {
    root.render(<Transcript rows={rows} />);
  });
  return host;
}

describe("session continuity after remount", () => {
  afterEach(() => {
    workspaceStore.reset(DEFAULT_STATE);
    document.body.replaceChildren();
  });

  it("keeps the selected session and prior user text after a remount", () => {
    workspaceStore.reset({ ...DEFAULT_STATE, session: "sess-1" });
    const items = [historicalItem(textFrame(0, "## Done\n\nA **plate**."), "sess-1")];
    const prompts = [{ seq: 0, text: "Add a **2 mm** chamfer." }];
    const rows = historicalRows(items, prompts);

    const first = mountTranscript(rows);
    expect(workspaceStore.getSnapshot().session).toBe("sess-1");
    expect(first.querySelector("[data-row='user-prompt']")?.textContent).toContain("2 mm");
    expect(first.querySelector("[data-markdown] strong")?.textContent).toBe("2 mm");
    expect(first.querySelector("[data-row='text'] h3, [data-row='text'] h4")?.textContent).toBe(
      "Done",
    );
    expect(first.textContent ?? "").not.toContain(HEDGE);

    first.remove();
    const second = mountTranscript(rows);
    expect(workspaceStore.getSnapshot().session).toBe("sess-1");
    expect(second.querySelector("[data-row='user-prompt']")?.textContent).toContain(
      "Add a **2 mm** chamfer.".replace("**", "").replace("**", ""),
    );
    expect(second.querySelector("[data-markdown]")?.textContent).toContain("2 mm");
    expect(second.querySelector("[data-absence]")).toBeNull();
    expect(second.textContent ?? "").not.toContain(HEDGE);
    expect(second.textContent ?? "").not.toContain(copy.stream.absence.terminal);
  });

  it("does not markdown-render tool-chip JSON", () => {
    const items = [
      historicalItem(
        {
          run_id: "sess-1",
          seq: 0,
          kind: "tool_call",
          tool_call_id: "c1",
          payload: { name: "inspect_part", arguments: { part: "tread" } },
        },
        "sess-1",
      ),
      historicalItem(
        {
          run_id: "sess-1",
          seq: 1,
          kind: "tool_result",
          tool_call_id: "c1",
          payload: { toolName: "inspect_part", text: '{"status":"ok"}', isError: false },
        },
        "sess-1",
      ),
    ];
    const host = mountTranscript(historicalRows(items));
    const chip = host.querySelector("[data-tool-name='inspect_part']");
    expect(chip).not.toBeNull();
    expect(chip?.querySelector("[data-markdown]")).toBeNull();
    expect(chip?.querySelector("h3, h4, h5")).toBeNull();
  });
});

describe("the composer textarea with no session", () => {
  afterEach(() => {
    workspaceStore.reset(DEFAULT_STATE);
    document.body.replaceChildren();
  });

  it("is not disabled when no session is selected", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    act(() => {
      root.render(
        <QueryClientProvider client={client}>
          <Composer
            sessionId={null}
            profile={null}
            attach={null}
            agentUnavailable={false}
            liveRunId={null}
            streamLive={true}
          />
        </QueryClientProvider>,
      );
    });
    const textarea = host.querySelector<HTMLTextAreaElement>("[data-composer-input]");
    expect(textarea).not.toBeNull();
    expect(textarea?.disabled).toBe(false);
    expect(textarea?.readOnly).toBe(false);
  });
});

describe("a finished historical turn", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("looks finished without a run-ended essay", () => {
    const items = [historicalItem(textFrame(0, "The chamfer is on the plate."), "sess-1")];
    const host = mountTranscript(panelRows(items, []));
    expect(host.querySelector("[data-row='terminal']")).toBeNull();
    expect(host.querySelector("[data-absence]")).toBeNull();
    expect(host.textContent ?? "").not.toContain(HEDGE);
    expect(host.textContent ?? "").toContain("The chamfer is on the plate.");
  });
});

// ---------------------------------------------------------------------------
// (h) §7.4, amended 2026-09-03 — the mid-run seam renders its OWN label, not
// the ordinary "End of the recorded transcript" one. `transcript.ts::panelRows`
// already computes the right `kind` on the seam row (`stream/transcript.ts`,
// tested directly in `transcript.test.ts`); what is asserted here is that the
// PRESENTATION layer actually reads it rather than always painting
// `copy.stream.seam`.
// ---------------------------------------------------------------------------

function seamRows(kind: "end" | "mid-run"): readonly PanelRow[] {
  const seam: PanelRow = { row: "seam", key: "seam", kind };
  return [
    ...historicalRows(
      [historicalItem(textFrame(0, "earlier turn"), "sess-seam")],
      [{ seq: 0, text: "the first question" }],
    ),
    seam,
  ];
}

describe("(h) the seam names which boundary it is", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("renders the ordinary label at the end of a run this tab held from the start", () => {
    const host = mountTranscript(seamRows("end"));
    const seam = host.querySelector("[data-seam]");
    expect(seam).not.toBeNull();
    expect(seam?.getAttribute("data-seam-kind")).toBe("end");
    expect(seam?.textContent ?? "").toContain("End of the recorded transcript");
  });

  it("renders a DIFFERENT label for a mid-run attach — never the end-of-transcript claim", () => {
    const host = mountTranscript(seamRows("mid-run"));
    const seam = host.querySelector("[data-seam]");
    expect(seam).not.toBeNull();
    expect(seam?.getAttribute("data-seam-kind")).toBe("mid-run");
    // The defect this amends: a mid-run attach painting "End of the recorded
    // transcript" over a run this tab did NOT hold from the start — a claim
    // the tab has no basis for.
    expect(seam?.textContent ?? "").not.toContain("End of the recorded transcript");
    expect(host.querySelectorAll("[data-seam]")).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// (g) §7A.5, amended 2026-09-03 — a refused echo is VISIBLY marked, not just
// carried in state. `transcript.ts::liveRows` already projects `state` /
// `refusedReason` from the echo entry onto the `local-prompt` row (tested in
// `live.test.ts`); this is the presentation half.
// ---------------------------------------------------------------------------

describe("(g) a refused echo is visibly marked, and never loses its text", () => {
  afterEach(() => {
    document.body.replaceChildren();
  });

  it("carries the unconditional default state 'sent' with no refusal reason", () => {
    const host = mountTranscript([
      { row: "local-prompt", key: "echo:0", text: "add a 3mm fillet" },
    ]);
    const row = host.querySelector("[data-row='local-prompt']");
    expect(row).not.toBeNull();
    expect(row?.getAttribute("data-echo-state")).toBe("sent");
  });

  it("marks a named refusal, keeps the sent words verbatim, and names the server's own reason", () => {
    const host = mountTranscript([
      {
        row: "local-prompt",
        key: "echo:0",
        text: "add a 3mm fillet",
        state: "refused",
        refusedReason: "run_in_flight",
      },
    ]);
    const row = host.querySelector("[data-row='local-prompt']");
    expect(row).not.toBeNull();
    expect(row?.getAttribute("data-echo-state")).toBe("refused");
    expect(row?.getAttribute("data-refused-reason")).toBe("run_in_flight");
    // C2's never-removed rule: the words are still there, verbatim.
    expect(row?.textContent ?? "").toContain("add a 3mm fillet");
    // No event id on a presentation row, refused or not.
    expect(row?.getAttribute("data-event-id")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// (f) §7A.5(C1)/§8, amended 2026-09-03 — the composer's OWN first turn, wired
// the way `StreamPanel` actually wires it: `useStream` feeds `Transcript`,
// `Composer`'s `onEcho`/`onEchoRefused` are `stream.echo`/`stream.refuseEcho`,
// and `sessionId` comes off the same workspace store `createSession`'s
// resolution writes to. No token is stored, so `useStream` never opens a
// socket (`workspaceToken()` is `null`) — the only way this echo can appear at
// all is through the create-then-send path itself, which is the point.
// ---------------------------------------------------------------------------

function Harness({ client }: { readonly client: QueryClient }): React.JSX.Element {
  const sessionId = useWorkspace((state) => state.session);
  const stream = useStream(sessionId);
  return (
    <QueryClientProvider client={client}>
      <Transcript rows={stream.rows} />
      <Composer
        sessionId={sessionId}
        profile={null}
        attach={null}
        agentUnavailable={false}
        liveRunId={null}
        streamLive={true}
        onEcho={stream.echo}
        onEchoRefused={stream.refuseEcho}
      />
    </QueryClientProvider>
  );
}

describe("(f) the composer's own first turn echoes into the session it just created", () => {
  afterEach(() => {
    workspaceStore.reset(DEFAULT_STATE);
    document.body.replaceChildren();
    vi.mocked(createSession).mockReset();
    vi.mocked(sendPrompt).mockReset();
    vi.mocked(fetchHistoryPage).mockReset();
    vi.mocked(fetchThread).mockReset();
  });

  it("mints the local-prompt row for the NEW session, before any live frame could arrive", async () => {
    const created: CreatedSessionDocument = {
      status: "ok",
      session_id: "sess-new",
      profile: "orchestrator",
      part: null,
      resumed: false,
    };
    vi.mocked(createSession).mockResolvedValue(created);
    // Left unresolved: nothing about the echo depends on the turn settling,
    // and settling it would only add noise to this assertion.
    vi.mocked(sendPrompt).mockImplementation(() => new Promise<PromptDocument>(() => undefined));
    vi.mocked(fetchHistoryPage).mockResolvedValue({
      status: "ok",
      session_id: "sess-new",
      events: [],
      user_prompts: [],
      cursor: null,
      done: true,
    });
    const thread: ThreadDocument = {
      status: "ok",
      session_id: "sess-new",
      thread_state: "unlinked",
      parent_session_id: null,
      nodes: [],
    };
    vi.mocked(fetchThread).mockResolvedValue(thread);

    const host = document.createElement("div");
    document.body.appendChild(host);
    const root = createRoot(host);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    act(() => {
      root.render(<Harness client={client} />);
    });

    const box = host.querySelector<HTMLTextAreaElement>("[data-composer-input]");
    expect(box).not.toBeNull();
    const setValue = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value",
    )?.set;
    act(() => {
      setValue?.call(box, "Ask about this plate.");
      box?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    act(() => {
      box?.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    // Flush the `createSession` promise and the re-renders it triggers.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(vi.mocked(createSession)).toHaveBeenCalledTimes(1);
    const echoRow = host.querySelector('[data-row="local-prompt"]');
    expect(echoRow).not.toBeNull();
    expect(echoRow?.textContent ?? "").toContain("Ask about this plate.");
    // The composer itself is now addressed to the session it minted.
    expect(host.querySelector("[data-composer]")?.getAttribute("data-session-id")).toBe("sess-new");
    act(() => {
      root.unmount();
    });
  });
});
