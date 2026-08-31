// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The rail's git axis (INTERFACE.md §13.1), as a DOM fragment.
//
// The first-slice screenshot of a live G4 fixture showed four untracked
// `.heph/blobs/sha256/…` rows wrapping into a multi-line ribbon that ate the
// left rail. Those paths are real git facts — §13.1 reports a dirty tree, never
// hides it — so the assertion is not that they vanish. It is that:
//
// * `<Fact>` still carries the server's path byte for byte (`data-value`);
// * the wrapper that *presents* the path is a single-line ellipsis host
//   (`[title]` is the full path, so hover is not a second source of truth);
// * `data-dirty` stays on the row, which is the selector the rest of the rail
//   already uses.
//
// No assertion is on a string of UI copy (§3).

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, afterEach } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { GitDirtyEntry, GitStatusDocument, PartsDocument } from "../src/api/types";
import { keys } from "../src/api/queries";
import { GitDirtyView, dirtySide, type DirtyIndex } from "../src/components/rail/GitDirty";
import {
  PROJECT_TREE_SECTIONS,
  ProjectSectionList,
  ProjectTree,
} from "../src/components/rail/ProjectTree";
import { Tree, TreeRow } from "../src/system";
import { DEFAULT_STATE } from "../src/state/workspace";
import { workspaceStore } from "../src/state/react";

const here = dirname(fileURLToPath(import.meta.url));
const pathCss = readFileSync(
  join(here, "..", "src", "components", "rail", "GitDirty.module.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");

const BLOB =
  ".heph/blobs/sha256/3c/3cc7d2c03c1e9f0a7b8d4e6f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b";

function render(element: ReactElement): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

function dirtyIndex(over: Partial<DirtyIndex> = {}): DirtyIndex {
  const blob: GitDirtyEntry = { path: BLOB, part: null, index: "?", worktree: "?" };
  return {
    byPart: new Map(),
    others: [blob],
    entries: [blob],
    clean: false,
    absence: null,
    ...over,
  };
}

describe("GitDirty — a long path outside parts/ stays one fact, one line", () => {
  it("attributes the server's path and does not hide it", () => {
    const host = render(<GitDirtyView index={dirtyIndex()} />);
    const fact = host.querySelector('[data-source="git.dirty[].path"]');
    expect(fact?.getAttribute("data-value")).toBe(BLOB);
    expect(host.querySelector('[data-dirty="untracked"]')).not.toBeNull();
  });

  it("puts the full path on title so the ellipsis is hoverable, not lost", () => {
    const host = render(<GitDirtyView index={dirtyIndex()} />);
    const wrap = host.querySelector(`[title="${BLOB}"]`);
    expect(wrap).not.toBeNull();
    expect(wrap?.querySelector('[data-source="git.dirty[].path"]')).not.toBeNull();
  });

  it("classifies an untracked blob as untracked, not as a part edit", () => {
    expect(
      dirtySide({ path: BLOB, part: null, index: "?", worktree: "?" }),
    ).toBe("untracked");
  });
});

describe("GitDirty.module.css — the wrapping the screenshot named", () => {
  it("declares the three DataTable tracks, not a two-column override", () => {
    // The two-column body put DataTable's empty unit cell on the next row.
    expect(pathCss).toMatch(
      /\.body\s*\{[^}]*grid-template-columns:\s*max-content minmax\(0,\s*1fr\) max-content/,
    );
  });

  it("truncates .path instead of word-breaking it", () => {
    expect(pathCss).toMatch(/\.path\s*\{[^}]*overflow:\s*hidden/);
    expect(pathCss).toMatch(/\.path\s*\{[^}]*text-overflow:\s*ellipsis/);
    expect(pathCss).toMatch(/\.path\s*\{[^}]*white-space:\s*nowrap/);
    expect(pathCss).not.toMatch(/word-break:\s*break-all/);
  });
});

describe("project tree sections — closed list, empty-honest", () => {
  it("lists the closed inventory even when every section is empty", () => {
    const host = render(<ProjectSectionList open={new Set()} onToggle={() => undefined} />);
    const rows = [...host.querySelectorAll('[data-tree-row="section"]')];
    expect(rows.map((node) => node.getAttribute("data-tree-section"))).toEqual([
      ...PROJECT_TREE_SECTIONS,
    ]);
    for (const row of rows) {
      expect(row.getAttribute("aria-expanded")).toBe("false");
    }
    expect(host.querySelector("[data-tree-section-empty]")).toBeNull();
    expect(host.querySelector("[data-source]")).toBeNull();
  });

  it("does not invent a catalog when a section is opened", () => {
    const host = render(
      <ProjectSectionList open={new Set(["materials"])} onToggle={() => undefined} />,
    );
    const empty = host.querySelector('[data-tree-section-empty="materials"]');
    expect(empty).not.toBeNull();
    expect(empty?.querySelector("[data-source]")).toBeNull();
    expect(host.querySelectorAll("[data-tree-section-empty]")).toHaveLength(1);
  });
});

describe("part row click selects the part", () => {
  let host: HTMLElement | undefined;
  let root: Root | undefined;

  afterEach(() => {
    act(() => {
      root?.unmount();
    });
    host?.remove();
    host = undefined;
    root = undefined;
    workspaceStore.reset(DEFAULT_STATE);
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

  function rowOf(container: HTMLElement, part: string): HTMLElement {
    const item = container.querySelector(`[data-tree-row="part"][data-part="${part}"]`);
    const row = item?.querySelector(":scope > div");
    if (!(row instanceof HTMLElement)) throw new Error(`no row for ${part}`);
    return row;
  }

  it("fires onSelect when a collapsed row is clicked", async () => {
    const seen: string[] = [];
    const container = await mount(
      <Tree label="parts">
        <TreeRow
          depth={0}
          selected={false}
          expanded={false}
          onSelect={() => {
            seen.push("shelf");
          }}
          onToggle={() => {
            seen.push("toggle");
          }}
          data-tree-row="part"
          data-part="shelf"
          label="shelf"
        />
      </Tree>,
    );
    await act(async () => {
      rowOf(container, "shelf").dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(seen).toEqual(["shelf"]);
  });

  it("selects on pointerdown so a focus remount cannot eat the click", async () => {
    const seen: string[] = [];
    const container = await mount(
      <Tree label="parts">
        <TreeRow
          depth={0}
          selected={false}
          expanded={false}
          onSelect={() => {
            seen.push("shelf");
          }}
          data-tree-row="part"
          data-part="shelf"
          label="shelf"
        />
      </Tree>,
    );
    await act(async () => {
      rowOf(container, "shelf").dispatchEvent(
        new MouseEvent("pointerdown", { bubbles: true, button: 0 }),
      );
    });
    expect(seen).toEqual(["shelf"]);
  });

  it("selects another part from the project tree without a hash edit", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const parts: PartsDocument = {
      status: "ok",
      parts: ["gusset", "shelf", "wall_plane"].map((name) => ({
        name,
        path: `parts/${name}.py`,
        content_hash: "sha256:x",
        snapshot_ref: `artifact:part-snapshot:sha256:${name}`,
      })),
    };
    const git: GitStatusDocument = {
      status: "ok",
      dirty: [],
      clean: true,
      head: "abc",
      branch: "main",
    };
    client.setQueryData(keys.parts(), parts);
    client.setQueryData(keys.gitStatus(), git);
    workspaceStore.reset({ ...DEFAULT_STATE, part: "gusset" });

    const container = await mount(
      <QueryClientProvider client={client}>
        <ProjectTree />
      </QueryClientProvider>,
    );
    expect(container.querySelector('[data-part="shelf"]')?.getAttribute("aria-selected")).toBe(
      "false",
    );
    await act(async () => {
      rowOf(container, "shelf").dispatchEvent(
        new MouseEvent("pointerdown", { bubbles: true, button: 0 }),
      );
    });
    expect(workspaceStore.getSnapshot().part).toBe("shelf");
  });
});
