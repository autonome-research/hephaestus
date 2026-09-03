// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// First-prompt memory for session tab titles (#51).
//
// A page-local supplement for the current page's first prompt — not the
// source of truth. After reload, `useStream` restores the opening line from
// `GET …/history`'s additive `user_prompts` field via `remember`. First write
// wins. A later turn is not a new conversation; the tab keeps the line the
// operator opened with. The snapshot is replaced, never mutated, so
// `useSyncExternalStore` identity comparison is a correct change test.

import { firstPromptLine } from "./sessionTitle";

type Listener = () => void;

const EMPTY: Readonly<Record<string, string>> = {};

/**
 * First prompt line per session id, as an external store.
 *
 * Not workspace state (§4.5's record is closed). A link does not need to
 * carry the sentence; the UUID in `?s=` is still the identity.
 */
export class SessionPromptStore {
  #byId: Readonly<Record<string, string>> = EMPTY;
  readonly #listeners = new Set<Listener>();

  subscribe = (listener: Listener): (() => void) => {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  };

  getSnapshot = (): Readonly<Record<string, string>> => this.#byId;

  /** Test / SSR seam: the same empty record, so identity stays stable. */
  getServerSnapshot = (): Readonly<Record<string, string>> => EMPTY;

  remember(sessionId: string, text: string): void {
    if (this.#byId[sessionId] !== undefined) return;
    const line = firstPromptLine(text);
    if (line === null) return;
    this.#commit({ ...this.#byId, [sessionId]: line });
  }

  /** Test seam: forget every prompt this page has sent. */
  reset(): void {
    this.#commit(EMPTY);
  }

  #commit(next: Readonly<Record<string, string>>): void {
    if (next === this.#byId) return;
    this.#byId = next;
    for (const listener of this.#listeners) listener();
  }
}

/** The process-wide store. One page, the prompts it has actually sent. */
export const sessionPromptStore = new SessionPromptStore();
