// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Well continuity after remount (INTERFACE.md §7.3, §8): session selection
// and recorded operator turns come back from history, not from the page store.
// The run-ended hedge does not enter the document.

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";
import { Transcript } from "../../src/components/stream/Transcript";
import { Composer } from "../../src/components/stream/Composer";
import { copy } from "../../src/copy";
import { DEFAULT_STATE } from "../../src/state/workspace";
import { workspaceStore } from "../../src/state/react";
import { historicalItem, historicalRows, panelRows } from "../../src/stream/transcript";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

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
