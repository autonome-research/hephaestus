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
//
// AMENDED 2026-09-03 — a fourth obligation, §2.8(5)/§8(h): the **tail read**.
// A walk retains the last page's `end_cursor` and a caller hands it back as
// `after` to read only what was recorded since, instead of re-walking and
// re-normalizing a whole session for one new turn. It is the same opaque token
// discipline: forwarded verbatim, never decoded, never persisted.
//
// AND ITS LIMIT, WHICH IS §8's RULE AND NOT A DETAIL: a tail read produces
// PREFIX material and nothing else. Live and historical events are never
// merged, and a tail read is NEVER used to fill a resync gap — §2.7 is explicit
// that history does not close a live gap, and the two identity namespaces do
// not compare. The one legal fold is a caller's: a tab may move a FINISHED run
// out of its live suffix into the prefix only by FIRST DISCARDING every live
// row of that run and then reading the tail, because the same logical events
// carry two disjoint identities and keeping both would render each one twice.
// A run is finished when the prompt response says so (§7A.6), never when the
// transcript merely looks quiet. This module hands back the token; it does not
// perform that fold, and it cannot: it can see only one surface.

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
  /**
   * §8(h) (amended 2026-09-03): the last page's `end_cursor` — the ordinal
   * AFTER this walk's last event, handed back as `after` to read the tail.
   *
   * OPTIONAL and `null` until a server sends one: `end_cursor` is additive and
   * a sidecar older than the amendment omits it, in which case there is no tail
   * read and the only honest value is "I do not have one".
   *
   * NOT `cursor`. `cursor` is `null` exactly when the walk is done; `end_cursor`
   * is present on every page INCLUDING the last and is never null when sent, so
   * the `cursor === null` test must not be reused on it.
   */
  readonly endCursor?: string | null;
}

export function emptyHistory(): HistoryProgress {
  return { items: [], userPrompts: [], pages: 0, state: "loading", error: null, endCursor: null };
}

/**
 * Read the additive `end_cursor` off a page.
 *
 * `HistoryPageDocument` (`api/sessions.ts`) declares it OPTIONAL, because a
 * sidecar older than the amendment sends no such field. It is read leniently on
 * top of that — anything that is not a non-empty string reads as absent, the
 * same discipline the `turn` fields get in `transcript.ts` — so a server that
 * sends `null`, or an empty token, yields "I have no tail cursor" rather than a
 * token that would be forwarded as `after` and refused.
 */
function readEndCursor(page: HistoryPageDocument): string | null {
  const value: unknown = page.end_cursor;
  return typeof value === "string" && value !== "" ? value : null;
}

/**
 * Fetch one page. `after` is §2.8(5)'s TAIL read and is passed on the FIRST
 * call of a tail walk only; a fetcher that predates it ignores the argument,
 * which is why it is last and optional.
 *
 * A call never carries both `cursor` and `after` — the route refuses that
 * (`invalid_cursor`, §2.4) — and `loadHistory` cannot produce one: the tail
 * token is consumed by the first request and every later request of the walk
 * carries the cursor the server handed back.
 */
export type PageFetcher = (
  sessionId: string,
  cursor: string | null,
  after?: string | null,
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
  after: string | null = null,
): Promise<HistoryProgress> {
  const items: TranscriptItem[] = [];
  const userPrompts: HistoryUserPrompt[] = [];
  let cursor: string | null = null;
  let tail: string | null = after;
  let endCursor: string | null = null;
  let pages = 0;
  for (;;) {
    if (signal?.aborted === true) {
      return { items, userPrompts, pages, state: "loading", error: null, endCursor };
    }
    let page: HistoryPageDocument;
    try {
      // The tail token opens the walk and is then dropped: page 2 of a tail
      // read is walked with the cursor the server minted over the mark it
      // froze, exactly like page 2 of a first read.
      page = await fetchPage(sessionId, cursor, tail);
      tail = null;
    } catch (cause) {
      const progress: HistoryProgress = {
        items,
        userPrompts,
        pages,
        state: "failed",
        error: cause instanceof Error ? cause : new Error(String(cause)),
        endCursor,
      };
      onPage(progress);
      return progress;
    }
    pages += 1;
    // LAST PAGE WINS, and it is never carried forward. §2.8(5) says `end_cursor`
    // is on EVERY page, so against a conforming server this is the same value
    // either way. Against one that sends it on some pages and not the page this
    // walk ended on, keeping the earlier token would name an ordinal BEFORE the
    // last item this walk already holds — handing that back as `after` would
    // re-read events the prefix already has and render each of them twice.
    // `null` is the honest answer there: no tail read is available.
    endCursor = readEndCursor(page);
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
      endCursor,
    };
    onPage(progress);
    if (finished || bounded) return progress;
    cursor = page.cursor;
  }
}
