// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// §7A.11 (C7) — the rail says which parts the turn touched.
//
// `refreshAfterTurn` extends its existing snapshot/diff to per-part build refs
// (the `content_hash`/`snapshot_ref` `GET /parts` already serves). Every rail
// row whose ref changed across the turn — created parts included — carries a
// transient `data-turn-changed`, cleared by exactly two things: the operator
// clicking that row, or the next turn's settle. The marker is a diff of TWO
// SERVER PROJECTIONS across a refetch — never a read of tool results — and it
// renders no value: it says *this changed*, not what it is now.
//
// Both sides of every rule are asserted: what marks, and what never marks.

import { describe, expect, it, afterEach, beforeEach } from "vitest";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { GitStatusDocument, PartsDocument } from "../src/api/types";
import { keys } from "../src/api/queries";
import {
  changedPartNames,
  partRefs,
  turnChangedStore,
} from "../src/api/refresh";
import { ProjectTree } from "../src/components/rail/ProjectTree";
import { DEFAULT_STATE } from "../src/state/workspace";
import { workspaceStore } from "../src/state/react";

function doc(rows: readonly (readonly [string, string, string])[]): PartsDocument {
  return {
    status: "ok",
    parts: rows.map(([name, hash, snap]) => ({
      name,
      path: `parts/${name}.py`,
      content_hash: hash,
      snapshot_ref: snap,
    })),
  };
}

describe("partRefs / changedPartNames — two server projections, one diff", () => {
  const before = partRefs(doc([
    ["bracket", "sha256:a", "artifact:part-snapshot:sha256:a"],
    ["panel", "sha256:b", "artifact:part-snapshot:sha256:b"],
  ]));

  it("marks a row whose content_hash changed, and only it", () => {
    const after = partRefs(doc([
      ["bracket", "sha256:a2", "artifact:part-snapshot:sha256:a"],
      ["panel", "sha256:b", "artifact:part-snapshot:sha256:b"],
    ]));
    expect(changedPartNames(before, after)).toEqual(["bracket"]);
  });

  it("marks a row whose snapshot_ref changed, and only it", () => {
    const after = partRefs(doc([
      ["bracket", "sha256:a", "artifact:part-snapshot:sha256:a"],
      ["panel", "sha256:b", "artifact:part-snapshot:sha256:b2"],
    ]));
    expect(changedPartNames(before, after)).toEqual(["panel"]);
  });

  it("includes a created part", () => {
    const after = partRefs(doc([
      ["bracket", "sha256:a", "artifact:part-snapshot:sha256:a"],
      ["panel", "sha256:b", "artifact:part-snapshot:sha256:b"],
      ["gusset", "sha256:c", "artifact:part-snapshot:sha256:c"],
    ]));
    expect(changedPartNames(before, after)).toEqual(["gusset"]);
  });

  it("marks nothing when no ref changed — the negative half", () => {
    const after = partRefs(doc([
      ["bracket", "sha256:a", "artifact:part-snapshot:sha256:a"],
      ["panel", "sha256:b", "artifact:part-snapshot:sha256:b"],
    ]));
    expect(changedPartNames(before, after)).toEqual([]);
  });

  it("never marks a removed part — there is no row left to mark", () => {
    const after = partRefs(doc([["panel", "sha256:b", "artifact:part-snapshot:sha256:b"]]));
    expect(changedPartNames(before, after)).toEqual([]);
  });

  it("does not collide hash and snapshot across the fold boundary", () => {
    // The two fields are joined with U+0000, so a byte moved across the
    // boundary is still a change, not an identical folded string.
    const x = partRefs(doc([["p", "sha256:ab", "c"]]));
    const y = partRefs(doc([["p", "sha256:a", "bc"]]));
    expect(changedPartNames(x, y)).toEqual(["p"]);
  });
});

describe("turnChangedStore — two exits, nothing else", () => {
  beforeEach(() => {
    turnChangedStore.settle([]);
  });

  it("settle marks exactly the named rows", () => {
    turnChangedStore.settle(["bracket"]);
    expect([...turnChangedStore.getSnapshot()]).toEqual(["bracket"]);
  });

  it("the next settle re-marks — old marks move to what THAT turn changed", () => {
    turnChangedStore.settle(["bracket"]);
    turnChangedStore.settle(["panel"]);
    const marked = turnChangedStore.getSnapshot();
    expect(marked.has("bracket")).toBe(false);
    expect(marked.has("panel")).toBe(true);
  });

  it("a settle with an empty diff clears every mark", () => {
    turnChangedStore.settle(["bracket", "panel"]);
    turnChangedStore.settle([]);
    expect(turnChangedStore.getSnapshot().size).toBe(0);
  });

  it("clear removes that row's mark and only it", () => {
    turnChangedStore.settle(["bracket", "panel"]);
    turnChangedStore.clear("bracket");
    const marked = turnChangedStore.getSnapshot();
    expect(marked.has("bracket")).toBe(false);
    expect(marked.has("panel")).toBe(true);
  });
});

describe("ProjectTree renders the transient mark (§7A.11 C7)", () => {
  let host: HTMLElement | undefined;
  let root: Root | undefined;

  beforeEach(() => {
    turnChangedStore.settle([]);
  });

  afterEach(() => {
    act(() => {
      root?.unmount();
    });
    host?.remove();
    turnChangedStore.settle([]);
  });

  async function mount(element: ReactElement): Promise<HTMLElement> {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => {
      root?.render(element);
    });
    return host;
  }

  function tree(): ReactElement {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(
      keys.parts(),
      doc([
        ["bracket", "sha256:a", "artifact:part-snapshot:sha256:a"],
        ["panel", "sha256:b", "artifact:part-snapshot:sha256:b"],
      ]),
    );
    client.setQueryData(keys.gitStatus(), {
      status: "ok",
      dirty: [],
      clean: true,
      head: "abc",
      branch: "main",
    } satisfies GitStatusDocument);
    workspaceStore.reset({ ...DEFAULT_STATE, part: null });
    return (
      <QueryClientProvider client={client}>
        <ProjectTree />
      </QueryClientProvider>
    );
  }

  it("marks exactly the changed row, with a marker that names no value", async () => {
    const container = await mount(tree());
    act(() => {
      turnChangedStore.settle(["bracket"]);
    });
    const marked = container.querySelectorAll("[data-turn-changed]");
    expect(marked).toHaveLength(1);
    expect(marked[0]?.getAttribute("data-part")).toBe("bracket");
    // The quiet marker rides the row; it carries no server value and no Fact.
    const marker = marked[0]?.querySelector("[data-turn-marker]");
    expect(marker).not.toBeNull();
    expect(marker?.hasAttribute("data-value")).toBe(false);
    expect(marker?.querySelector("[data-source]")).toBeNull();
  });

  it("never marks a row the diff did not name — the negative half", async () => {
    const container = await mount(tree());
    expect(container.querySelector("[data-turn-changed]")).toBeNull();
    act(() => {
      turnChangedStore.settle(["panel"]);
    });
    expect(
      container.querySelector('[data-part="bracket"][data-turn-changed]'),
    ).toBeNull();
  });

  it("clears on the operator clicking that row, and survives other clicks", async () => {
    const container = await mount(tree());
    act(() => {
      turnChangedStore.settle(["bracket", "panel"]);
    });
    const row = container
      .querySelector('[data-tree-row="part"][data-part="bracket"]')
      ?.querySelector(":scope > div");
    expect(row).not.toBeNull();
    await act(async () => {
      row?.dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0 }));
    });
    expect(
      container.querySelector('[data-part="bracket"][data-turn-changed]'),
    ).toBeNull();
    // The unclicked row keeps its mark: per-row, not per-panel.
    expect(
      container.querySelector('[data-part="panel"][data-turn-changed]'),
    ).not.toBeNull();
  });

  it("moves when the next turn settles a different diff", async () => {
    const container = await mount(tree());
    act(() => {
      turnChangedStore.settle(["bracket"]);
    });
    act(() => {
      turnChangedStore.settle(["panel"]);
    });
    expect(
      container.querySelector('[data-part="bracket"][data-turn-changed]'),
    ).toBeNull();
    expect(
      container.querySelector('[data-part="panel"][data-turn-changed]'),
    ).not.toBeNull();
  });
});
