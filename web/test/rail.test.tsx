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
// The 2026-09-01 operator review added the half one line each did not fix: 37 of
// them is 37 lines, and on the live fixture every one was the workspace's own
// `.heph/` store, pushing the part tree and the providers sign-in out of a 280px
// rail. So the assertions above are now made **through the disclosure**: the
// `.heph/` rows are one counted row, opening it yields exactly the same table,
// and a path the operator actually authored is never grouped.
//
// No assertion is on a string of UI copy (§3).

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, afterEach, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { createRoot, type Root } from "react-dom/client";
import { act } from "react";
import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { GitDirtyEntry, GitStatusDocument, PartsDocument } from "../src/api/types";
import { WorkspaceError } from "../src/api/client";
import { keys } from "../src/api/queries";
import { claimToken, dropToken } from "../src/api/token";
import { copy } from "../src/copy";
import {
  GitDirtyView,
  dirtySide,
  gitCapabilityAbsence,
  indexDirty,
  isGeneratedPath,
  railBranch,
  railHead,
  type DirtyIndex,
} from "../src/components/rail/GitDirty";
import { VersionList } from "../src/components/rail/VersionList";
import {
  PROJECT_TREE_SECTIONS,
  ProjectSectionList,
  ProjectTree,
} from "../src/components/rail/ProjectTree";
import { Tree, TreeRow, formatOid } from "../src/system";
import { DEFAULT_STATE } from "../src/state/workspace";
import { workspaceStore } from "../src/state/react";

const here = dirname(fileURLToPath(import.meta.url));
const pathCss = readFileSync(
  join(here, "..", "src", "components", "rail", "GitDirty.module.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");

const BLOB =
  ".heph/blobs/sha256/3c/3cc7d2c03c1e9f0a7b8d4e6f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b";
/** A path the operator wrote, outside `parts/` and outside the generated store. */
const AUTHORED = "docs/assembly-notes.md";

function render(element: ReactElement): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(element);
  return host;
}

/** A live root, for the assertions that have to open a disclosure first. */
function live(element: ReactElement): { host: HTMLElement; root: Root } {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => {
    root.render(element);
  });
  return { host, root };
}

function refuseAll(): void {
  window.history.replaceState(null, "", "/#t=rail-test-token");
  claimToken();
  vi.stubGlobal(
    "fetch",
    async () =>
      new Response(JSON.stringify({ status: "error", reason: "transport_error", message: "refused" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      }),
  );
}

async function flush(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => {
      setTimeout(resolve, 0);
    });
  });
}

function drop(mounted: { host: HTMLElement; root: Root }): void {
  act(() => {
    mounted.root.unmount();
  });
  mounted.host.remove();
}

function dirtyIndex(over: Partial<DirtyIndex> = {}): DirtyIndex {
  const blob: GitDirtyEntry = { path: BLOB, part: null, index: "?", worktree: "?" };
  return {
    byPart: new Map(),
    others: [blob],
    entries: [blob],
    clean: false,
    absence: null,
    error: null,
    branch: null,
    head: null,
    ...over,
  };
}

describe("GitDirty — a long path outside parts/ stays one fact, one line", () => {
  function open(host: HTMLElement): void {
    const group = host.querySelector<HTMLElement>('[data-dirty-group="generated"]');
    if (group === null) throw new Error("no generated group to open");
    act(() => {
      group.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
  }

  it("attributes the server's path and does not hide it", () => {
    const mounted = live(<GitDirtyView index={dirtyIndex()} />);
    try {
      open(mounted.host);
      const fact = mounted.host.querySelector('[data-source="git.dirty[].path"]');
      expect(fact?.getAttribute("data-value")).toBe(BLOB);
      expect(mounted.host.querySelector('[data-dirty="untracked"]')).not.toBeNull();
    } finally {
      drop(mounted);
    }
  });

  it("puts the full path on title so the ellipsis is hoverable, not lost", () => {
    const mounted = live(<GitDirtyView index={dirtyIndex()} />);
    try {
      open(mounted.host);
      const wrap = mounted.host.querySelector(`[title="${BLOB}"]`);
      expect(wrap).not.toBeNull();
      expect(wrap?.querySelector('[data-source="git.dirty[].path"]')).not.toBeNull();
    } finally {
      drop(mounted);
    }
  });

  it("classifies an untracked blob as untracked, not as a part edit", () => {
    expect(
      dirtySide({ path: BLOB, part: null, index: "?", worktree: "?" }),
    ).toBe("untracked");
  });
});

describe("GitDirty — the generated store is one counted row, not 37", () => {
  const blob: GitDirtyEntry = { path: BLOB, part: null, index: "?", worktree: "?" };
  const db: GitDirtyEntry = { path: ".heph/state.db", part: null, index: "?", worktree: "?" };
  const authored: GitDirtyEntry = { path: AUTHORED, part: null, index: ".", worktree: "M" };

  function index(others: readonly GitDirtyEntry[]): DirtyIndex {
    return dirtyIndex({ others, entries: others });
  }

  it("collapses .heph/ paths behind one row carrying their count", () => {
    const host = render(<GitDirtyView index={index([blob, db, authored])} />);
    const group = host.querySelector('[data-dirty-group="generated"]');
    expect(group?.getAttribute("data-dirty-group-count")).toBe("2");
    expect(group?.getAttribute("aria-expanded")).toBe("false");
    // Collapsed: the generated paths are one row, not two tables' worth of rows.
    expect(host.querySelector(`[title="${BLOB}"]`)).toBeNull();
    expect(host.querySelectorAll('[data-source="git.dirty[].path"]')).toHaveLength(1);
  });

  it("never groups a path the operator authored", () => {
    const host = render(<GitDirtyView index={index([blob, authored])} />);
    const shown = [...host.querySelectorAll('[data-source="git.dirty[].path"]')].map((node) =>
      node.getAttribute("data-value"),
    );
    expect(shown).toEqual([AUTHORED]);
    expect(isGeneratedPath(AUTHORED)).toBe(false);
    expect(isGeneratedPath(BLOB)).toBe(true);
    expect(isGeneratedPath(".heph/state.db")).toBe(true);
  });

  it("draws no group row at all when nothing generated is dirty", () => {
    const host = render(<GitDirtyView index={index([authored])} />);
    expect(host.querySelector("[data-dirty-group]")).toBeNull();
    expect(host.querySelectorAll('[data-source="git.dirty[].path"]')).toHaveLength(1);
  });

  it("still reports the server's own total, group or no group", () => {
    // §1: the caption is the length of the array `git status` served, and the
    // grouping is presentation — it never changes the number the panel prints.
    const host = render(<GitDirtyView index={index([blob, db, authored])} />);
    expect(host.textContent).toContain("3");
  });
});

describe("GitDirty — §13.1's git identity is on the git axis", () => {
  const OID = "aabbccddeeff0011223344556677889900112233";

  it("prints branch and an abbreviated HEAD in the rail, with the whole oid attributed", () => {
    const host = render(
      <GitDirtyView index={dirtyIndex({ branch: "main", head: OID, others: [], entries: [] })} />,
    );
    expect(host.querySelector('[data-source="git.branch"]')?.getAttribute("data-value")).toBe("main");
    const head = host.querySelector('[data-source="git.head"]');
    expect(head?.getAttribute("data-value")).toBe(OID);
    // The 44px header bar printed the whole 40-glyph oid because
    // `formatRef(head, 8)` sliced from the end. A prefix is a prefix.
    expect(head?.textContent).toBe(formatOid(OID));
    expect(head?.textContent?.length).toBe(8);
  });

  it("treats porcelain (detached) as no branch and refuses HEAD without an oid", () => {
    expect(railBranch("(detached)")).toBeNull();
    expect(railBranch("")).toBeNull();
    expect(railBranch("main")).toBe("main");
    expect(railHead("HEAD")).toBeNull();
    expect(railHead("not-a-sha")).toBeNull();
    expect(railHead(OID)).toBe(OID);
    const host = render(<GitDirtyView index={dirtyIndex({ branch: null, head: null })} />);
    expect(host.querySelector('[data-source="git.branch"]')).toBeNull();
    expect(host.querySelector('[data-source="git.head"]')).toBeNull();
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
    vi.unstubAllGlobals();
    dropToken();
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

  it("prints a refusal, not Loading…, when GET /parts is refused (#89)", async () => {
    refuseAll();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(keys.gitStatus(), {
      status: "ok",
      dirty: [],
      clean: true,
      head: "abc",
      branch: "main",
    } satisfies GitStatusDocument);
    const container = await mount(
      <QueryClientProvider client={client}>
        <ProjectTree />
      </QueryClientProvider>,
    );
    await flush();
    expect(container.querySelector('[data-refusal-reason="transport_error"]')).not.toBeNull();
    expect(container.textContent).not.toContain(copy.absent.loading);
  });
});

describe("GitDirty — refused is not loading, and orphans still get a row", () => {
  const status = (
    dirty: readonly GitDirtyEntry[],
  ): GitStatusDocument => ({
    status: "ok",
    dirty,
    clean: dirty.length === 0,
    head: "abc",
    branch: "main",
  });

  it("names only git_unavailable and not_a_git_repository as capability absences (#89)", () => {
    expect(gitCapabilityAbsence(new WorkspaceError(503, "git_unavailable", "no git"))).toBe(
      copy.absent.gitUnavailable,
    );
    expect(gitCapabilityAbsence(new WorkspaceError(404, "not_a_git_repository", "no repo"))).toBe(
      copy.absent.noGit,
    );
    expect(gitCapabilityAbsence(new WorkspaceError(500, "transport_error", "boom"))).toBeNull();
    expect(gitCapabilityAbsence(new Error("socket"))).toBeNull();
  });

  it("prints a refusal, not Loading…, when git status is a 500 (#89)", () => {
    const err = new WorkspaceError(500, "transport_error", "boom");
    const host = render(<GitDirtyView index={dirtyIndex({ error: err, clean: null })} />);
    expect(host.querySelector('[data-refusal-reason="transport_error"]')).not.toBeNull();
    expect(host.textContent).not.toContain(copy.absent.loading);
  });

  it("still prints Loading… only while the fetch is in flight (#89)", () => {
    const host = render(<GitDirtyView index={dirtyIndex({ clean: null, error: null })} />);
    expect(host.textContent).toContain(copy.absent.loading);
    expect(host.querySelector("[data-refusal-reason]")).toBeNull();
  });

  it("places a deleted part's dirty path on a row, not only in the caption (#95)", () => {
    const orphan: GitDirtyEntry = {
      path: "parts/old_bracket.py",
      part: "old_bracket",
      index: "D",
      worktree: ".",
    };
    const live: GitDirtyEntry = {
      path: "parts/gusset.py",
      part: "gusset",
      index: "M",
      worktree: ".",
    };
    const index = indexDirty(status([orphan, live]), null, new Set(["gusset"]));
    expect(index.byPart.has("gusset")).toBe(true);
    expect(index.byPart.has("old_bracket")).toBe(false);
    expect(index.others.map((entry) => entry.path)).toEqual(["parts/old_bracket.py"]);
    expect(index.entries).toHaveLength(2);
    const host = render(<GitDirtyView index={index} />);
    expect(host.textContent).toContain("2");
    expect(
      [...host.querySelectorAll('[data-source="git.dirty[].path"]')].map((node) =>
        node.getAttribute("data-value"),
      ),
    ).toEqual(["parts/old_bracket.py"]);
  });

  it("does not drop a second dirty path on the same part (#95)", () => {
    const deleted: GitDirtyEntry = {
      path: "parts/old_name.py",
      part: "bracket",
      index: "D",
      worktree: ".",
    };
    const added: GitDirtyEntry = {
      path: "parts/bracket.py",
      part: "bracket",
      index: "?",
      worktree: "?",
    };
    const index = indexDirty(status([deleted, added]), null, new Set(["bracket"]));
    expect(index.byPart.get("bracket")?.path).toBe("parts/old_name.py");
    expect(index.others.map((entry) => entry.path)).toEqual(["parts/bracket.py"]);
    expect(index.byPart.size + index.others.length).toBe(index.entries.length);
  });
});

describe("VersionList — refused is not loading", () => {
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
    vi.unstubAllGlobals();
    dropToken();
  });

  it("prints a refusal, not Loading…, when GET /git/log is refused (#89)", async () => {
    refuseAll();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(keys.gitStatus(), {
      status: "ok",
      dirty: [],
      clean: true,
      head: "abc",
      branch: "main",
    } satisfies GitStatusDocument);
    client.setQueryData(keys.parts(), {
      status: "ok",
      parts: [],
    } satisfies PartsDocument);
    workspaceStore.reset({ ...DEFAULT_STATE, part: "gusset" });
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    await act(async () => {
      root?.render(
        <QueryClientProvider client={client}>
          <VersionList />
        </QueryClientProvider>,
      );
    });
    await flush();
    expect(host.querySelector('[data-refusal-reason="transport_error"]')).not.toBeNull();
    expect(host.textContent).not.toContain(copy.absent.loading);
  });
});
