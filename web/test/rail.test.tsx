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
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";

import type { GitDirtyEntry } from "../src/api/types";
import { GitDirtyView, dirtySide, type DirtyIndex } from "../src/components/rail/GitDirty";

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
