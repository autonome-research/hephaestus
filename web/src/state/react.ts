// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The React binding for the one workspace store, and the URL sync (§4.5).
//
// `useSyncExternalStore` and no state library: §3's decision, and the reason it
// works here is that the store is the single pin authority. Components read a
// *selected slice* so a slider drag does not re-render the rail, and every write
// goes through the store's four doors (`update`, `hold`, `followCurrent`,
// `observeCurrent`).
//
// **The URL is a projection of the store, never a second source.** The store
// commits, then the hash is rewritten to match; a `hashchange` the app did not
// author (Back/Forward, a pasted link) is decoded and `reset` onto the store.
// A two-way binding where both sides could win is how a pin drifts, and §4.5's
// whole point is that the pin has one authority.

import { useSyncExternalStore } from "react";
import {
  DEFAULT_STATE,
  WorkspaceStore,
  decodeWorkspaceUrl,
  encodeWorkspaceUrl,
  type WorkspaceState,
} from "./workspace";

/** The process-wide store. One workspace, one pin. */
export const workspaceStore = new WorkspaceStore(DEFAULT_STATE);

/**
 * Hydrate from the current hash and keep the two in step for the app's life.
 *
 * Returns a teardown. Call **after** `claimToken()` has taken `#t=` out of the
 * fragment, so the router never sees a token where a route belongs.
 */
export function startUrlSync(store: WorkspaceStore = workspaceStore): () => void {
  store.reset(decodeWorkspaceUrl(window.location.hash));

  let writing = false;
  let lastPart = store.getSnapshot().part;

  const push = (): void => {
    const state = store.getSnapshot();
    const next = encodeWorkspaceUrl(state);
    if (window.location.hash === next) return;
    writing = true;
    try {
      // A new part is a navigation and earns a history entry. A camera nudge, a
      // tab, or a slider tick is not: `pushState` per frame would make Back
      // useless, which is a worse failure than a missing entry.
      const url = window.location.pathname + window.location.search + next;
      if (state.part !== lastPart) window.history.pushState(null, "", url);
      else window.history.replaceState(null, "", url);
      lastPart = state.part;
    } finally {
      writing = false;
    }
  };

  const onHashChange = (): void => {
    if (writing) return;
    store.reset(decodeWorkspaceUrl(window.location.hash));
  };

  const unsubscribe = store.subscribe(push);
  window.addEventListener("hashchange", onHashChange);
  window.addEventListener("popstate", onHashChange);
  push();

  return () => {
    unsubscribe();
    window.removeEventListener("hashchange", onHashChange);
    window.removeEventListener("popstate", onHashChange);
  };
}

/** Read a slice of workspace state. The selector must be referentially stable. */
export function useWorkspace<T>(select: (state: WorkspaceState) => T): T {
  return useSyncExternalStore(
    workspaceStore.subscribe,
    () => select(workspaceStore.getSnapshot()),
    () => select(DEFAULT_STATE),
  );
}

/** The whole record, for the rare consumer that needs all of it. */
export function useWorkspaceState(): WorkspaceState {
  return useSyncExternalStore(
    workspaceStore.subscribe,
    workspaceStore.getSnapshot,
    () => DEFAULT_STATE,
  );
}
