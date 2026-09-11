// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// `useBreakpoint` — the SOLE authority for §4.1's breakpoints.
//
// Width is capacity, not intent: applyWidth clamps dimensions and chooses
// Parts column/overlay capacity without writing conversation open state. The
// client shell presentation store is separate from §4.5's URL record. CSS
// consumes React's data-stream/data-rail and has no competing grid media query.
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
