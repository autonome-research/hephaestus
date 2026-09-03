// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Multi-page transcript loading (INTERFACE.md §8, binding G4.9).
//
// §8: "On reopen: `GET /sessions/{id}/thread` for structure, then paged
// `GET /sessions/{id}/history` per session with the cursor forwarded verbatim
// until `done`. The panel renders progressively and shows a page counter —
// 'multi-page' is a user-visible fact, not only a test fact."
//
// Three obligations, and each is a line of code you can point at:
//
// 1. **The cursor is forwarded verbatim.** It is opaque base64url over
//    `{hw, offset}` and it freezes a high-water mark on page 1. This loader
//    reads `page.cursor`, passes it to the next call, and never inspects,
//    decodes, rewrites, or persists it. There is no page-size parameter to pass
//    and none is invented (§2.8, §15.11).
// 2. **Progressive rendering.** `onPage` fires per page, so a 300-event
//    transcript paints its first 250 while the second page is in flight rather
//    than after it.
// 3. **The page count is a user-visible fact.** It is the number of pages the
//    server actually served — counted from responses, never estimated from an
//    event total divided by a page size the client is not allowed to know.
//
// The loop is bounded. `done` ends it; `MAX_HISTORY_PAGES` ends it too, and says
// so, because a server that never sets `done` would otherwise spin a browser tab
// forever. Reaching the bound is reported as a **stated truncation**, not as a
// completed load — §4.4's discipline applied to paging.

import type { HistoryPageDocument, HistoryUserPrompt } from "../api/sessions";
import { historicalItem, type TranscriptItem } from "./transcript";

/**
 * The page ceiling. `HISTORY_PAGE_SIZE` is 250 in the sidecar, so this bounds a
 * single reopen at 100k normalized events — far past any real transcript, and
 * finite, which is the property that matters.
 */
export const MAX_HISTORY_PAGES = 400;

export type HistoryLoadState = "loading" | "complete" | "truncated" | "failed";

export interface HistoryProgress {
  readonly items: readonly TranscriptItem[];
  readonly userPrompts: readonly HistoryUserPrompt[];
  readonly pages: number;
  readonly state: HistoryLoadState;
  readonly error: Error | null;
}

export function emptyHistory(): HistoryProgress {
  return { items: [], userPrompts: [], pages: 0, state: "loading", error: null };
}

export type PageFetcher = (
  sessionId: string,
  cursor: string | null,
) => Promise<HistoryPageDocument>;

/**
 * Page a session's history to `done`, reporting each page as it lands.
 *
 * `onPage` receives the cumulative progress so a caller can render it directly.
 * `signal` lets a caller abandon a load — switching session tabs mid-load must
 * not append the old session's pages onto the new session's transcript, which
 * would be a merge of two transcripts and is exactly what §8 forbids between
 * two *surfaces*, for the same reason.
 */
export async function loadHistory(
  sessionId: string,
  fetchPage: PageFetcher,
  onPage: (progress: HistoryProgress) => void,
  signal?: { readonly aborted: boolean },
): Promise<HistoryProgress> {
  const items: TranscriptItem[] = [];
  const userPrompts: HistoryUserPrompt[] = [];
  let cursor: string | null = null;
  let pages = 0;
  for (;;) {
    if (signal?.aborted === true) {
      return { items, userPrompts, pages, state: "loading", error: null };
    }
    let page: HistoryPageDocument;
    try {
      page = await fetchPage(sessionId, cursor);
    } catch (cause) {
      const progress: HistoryProgress = {
        items,
        userPrompts,
        pages,
        state: "failed",
        error: cause instanceof Error ? cause : new Error(String(cause)),
      };
      onPage(progress);
      return progress;
    }
    pages += 1;
    for (const frame of page.events) {
      // The page's own `session_id`, not the frame's `run_id` — §2.8's misnomer.
      items.push(historicalItem(frame, page.session_id));
    }
    for (const prompt of page.user_prompts ?? []) {
      userPrompts.push(prompt);
    }
    const finished = page.done || page.cursor === null;
    const bounded = !finished && pages >= MAX_HISTORY_PAGES;
    const progress: HistoryProgress = {
      items: [...items],
      userPrompts: [...userPrompts],
      pages,
      state: finished ? "complete" : bounded ? "truncated" : "loading",
      error: null,
    };
    onPage(progress);
    if (finished || bounded) return progress;
    cursor = page.cursor;
  }
}
