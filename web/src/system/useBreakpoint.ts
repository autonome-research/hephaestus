// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `useBreakpoint` — the SOLE authority for §4.1's breakpoints.
//
// §4.1's 2026-08-28 TIGHTENING (binds G4's shell deliverable): "`useBreakpoint.ts`
// is the **sole** authority. It writes `streamOpen` / `railOverlay` into
// workspace state; `Shell.module.css` keeps **no** media query that changes
// `grid-template-columns`; the grid is driven by `data-stream` and `data-rail`,
// which React sets."
//
// The measurement that convicts the shipped arrangement is in `state/shell.ts`'s
// header, along with the one deviation this implementation takes (the three
// fields live in a shell store rather than in §4.5's closed, URL-serialized
// record). What matters here is the shape of the fix: **exactly one party reads
// the viewport width**, and it is this hook. `Shell.module.css` reads
// `[data-stream]` and `[data-rail]` and never a media query for the grid, so the
// two cannot disagree between 1024 and 1279px — which is where they did.
//
// `ResizeObserver` on the document element rather than a `resize` listener: it
// fires for a devtools dock and a zoom change too, both of which move the layout
// without a window resize event, and Playwright's `setViewportSize` produces
// either depending on the browser.

import { useEffect, useSyncExternalStore } from "react";
import { shellStore, type ShellState } from "../state/shell";

/** The current shell layout. Read-only; writes go through the returned actions. */
export function useShell(): ShellState {
  return useSyncExternalStore(shellStore.subscribe, shellStore.getSnapshot, shellStore.getSnapshot);
}

/**
 * Install the one width observer and read the current shell state.
 *
 * Mount this **once**, in the shell. Mounting it twice is harmless (the store
 * de-duplicates a band that has not changed) but it would be a second party
 * looking at the width, which is the thing this hook exists to prevent.
 */
export function useBreakpoint(): ShellState {
  const state = useShell();

  useEffect(() => {
    const element = document.documentElement;
    const measure = (): void => {
      shellStore.applyWidth(element.clientWidth);
    };
    measure();
    // jsdom has no ResizeObserver; the hook is still correct there because
    // `measure()` above has already run and no resize follows in a unit test.
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);

  return state;
}

export { BREAKPOINT_RAIL, BREAKPOINT_STREAM, bandFor, shellStore } from "../state/shell";
export type { Band, ShellState } from "../state/shell";
