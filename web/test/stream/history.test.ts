// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Multi-page transcript loading (INTERFACE.md §8, §2.8, binding G4.9).

import { describe, expect, it, vi } from "vitest";
import { fetchHistoryPage } from "../../src/api/sessions";
import { loadHistory, MAX_HISTORY_PAGES } from "../../src/stream/history";
import type { HistoryPageDocument } from "../../src/api/sessions";
import { fixture } from "./fixture";

function pager(): {
  fetchPage: (sessionId: string, cursor: string | null) => Promise<HistoryPageDocument>;
  cursors: (string | null)[];
} {
  const cursors: (string | null)[] = [];
  let index = 0;
  const fetchPage = (_sessionId: string, cursor: string | null): Promise<HistoryPageDocument> => {
    cursors.push(cursor);
    const page = fixture.pages[index];
    index += 1;
    if (page === undefined) throw new Error("fetched past the recorded pages");
    return Promise.resolve(page);
  };
  return { fetchPage, cursors };
}

describe("paging to done (G4.9)", () => {
  it("is genuinely multi-page: the recorded transcript exceeds one page", () => {
    // §2.8 makes ">250 normalized events" a fixture requirement precisely so
    // this is not vacuous. The recorder produced the pages through the sidecar's
    // own `pageHistory`, at its own `HISTORY_PAGE_SIZE`.
    expect(fixture.pages.length).toBeGreaterThan(1);
    expect(fixture.pages[0]?.events.length).toBe(250);
    expect(fixture.pages[0]?.done).toBe(false);
  });

  it("follows the cursor to done and accumulates every event", () => {
    const { fetchPage, cursors } = pager();
    return loadHistory(fixture.session_id, fetchPage, () => undefined).then((progress) => {
      expect(progress.state).toBe("complete");
      expect(progress.pages).toBe(fixture.pages.length);
      expect(progress.items.length).toBe(
        fixture.pages.reduce((n, page) => n + page.events.length, 0),
      );
      // The first call carries no cursor; every later call carries the previous
      // page's cursor **verbatim**.
      expect(cursors[0]).toBeNull();
      expect(cursors[1]).toBe(fixture.pages[0]?.cursor);
    });
  });

  it("reports each page as it lands, so the panel paints progressively", () => {
    const { fetchPage } = pager();
    const seen: number[] = [];
    return loadHistory(fixture.session_id, fetchPage, (progress) => {
      seen.push(progress.items.length);
    }).then(() => {
      expect(seen).toEqual([250, 306]);
    });
  });

  it("keeps events in page order, so ordinals stay monotonic across the boundary", () => {
    const { fetchPage } = pager();
    return loadHistory(fixture.session_id, fetchPage, () => undefined).then((progress) => {
      const seqs = progress.items.map((item) => item.seq);
      for (let i = 1; i < seqs.length; i += 1) {
        expect(seqs[i]).toBe((seqs[i - 1] ?? -1) + 1);
      }
    });
  });

  it("stops when a caller abandons the load", () => {
    const { fetchPage } = pager();
    const signal = { aborted: true };
    return loadHistory(fixture.session_id, fetchPage, () => undefined, signal).then((progress) => {
      expect(progress.pages).toBe(0);
      expect(progress.items).toEqual([]);
    });
  });

  it("surfaces a refusal instead of silently ending the transcript", () => {
    const failing = (): Promise<HistoryPageDocument> => Promise.reject(new Error("503"));
    return loadHistory(fixture.session_id, failing, () => undefined).then((progress) => {
      expect(progress.state).toBe("failed");
      expect(progress.error?.message).toBe("503");
    });
  });

  it("bounds the loop against a server that never says done", () => {
    const endless = (): Promise<HistoryPageDocument> =>
      Promise.resolve({
        status: "ok",
        session_id: fixture.session_id,
        events: [],
        cursor: "never-ending",
        done: false,
      });
    return loadHistory(fixture.session_id, endless, () => undefined).then((progress) => {
      expect(progress.pages).toBe(MAX_HISTORY_PAGES);
      // A stated truncation, not a completed load.
      expect(progress.state).toBe("truncated");
    });
  });
});

describe("the cursor is opaque (§2.8, §15.11)", () => {
  it("sends the cursor byte-for-byte and asks for no page size", async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      calls.push(String(input));
      return Promise.resolve(
        new Response(JSON.stringify({ status: "ok", session_id: "s", events: [], cursor: null, done: true }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    });
    const original = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    const { claimToken } = await import("../../src/api/token");
    window.location.hash = "#t=test-token";
    claimToken();
    try {
      const cursor = fixture.pages[0]?.cursor;
      expect(cursor).toBeTypeOf("string");
      await fetchHistoryPage("sess-1", cursor ?? null);
      const url = calls[0] ?? "";
      expect(url).toContain(`cursor=${cursor ?? ""}`);
      expect(url).not.toContain("page_size");
      expect(url).not.toContain("limit");
    } finally {
      globalThis.fetch = original;
    }
  });
});
