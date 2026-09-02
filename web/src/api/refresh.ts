// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The read-refresh boundary (INTERFACE.md §7A.11, §19.28).
//
// THE DEFECT THIS CLOSES, stated first because it is the whole reason the module
// exists. The composer makes the browser the **originator** of agent mutations
// for the first time. Nothing in `web/src` refreshed the read caches when the
// agent wrote: `queries.ts` defines nine keys and a 5s project staleness, and no
// mutation path invalidated any of them. The blank-canvas flow would therefore
// have ended with a transcript full of successful tool calls and a rail that
// still said the project has no parts — an agent that says it worked and a
// workspace that shows it did not.
//
// TWO RULES, both normative, both enforced here rather than trusted:
//
// **1. Refetch, never merge.** §7A.11's TIGHTENING binds §1: the invalidation is
// a refetch of the *server projection*, never a client-side merge of tool
// results. A composer that patched the parts list from a `create_part` result
// would be the client deriving the project's shape from an event payload — the
// exact failure §1 and `heph/no-derived-fact` exist to prevent, arriving through
// a door §1 did not have to consider before the browser could start runs. That
// is why this module's whole surface is a list of *keys*: there is nowhere to
// put a payload, so there is nothing to merge.
//
// **2. A held pin does not move.** §4.5's sticky-pin tightening (binding G5.6)
// is untouched: `observeCurrent` is already a no-op while held. The 2026-09-01
// amendment under §4.5 adds one *selection* act after `create_part`: when the
// tree grows a name it did not have and `pin_mode` is `"current"`, the
// workspace selects that part so `observeCurrent` can follow its build. A pin
// whose mode is `"pinned"` is not auto-advanced. The fixture-default empty
// part is not a held pin the operator chose.
//
// WHEN IT FIRES (§7A.11): on a `terminal` frame for a run on this project, and
// on the prompt response, which §7A.6 already makes the authority for turn
// completion. Both, not either: the response is the guarantee the originating
// tab gets, and the terminal frame is what an observer tab has.

import type { QueryClient } from "@tanstack/react-query";
import { workspaceStore } from "../state/react";
import type { WorkspaceStore } from "../state/workspace";
import { keys } from "./queries";
import type { PartsDocument } from "./types";

/**
 * The keys §7A.11 enumerates, resolved for one part.
 *
 * Exported as data so the test asserts the **list** rather than the effect of
 * calling it: §7A.11 names nine keys, and a key quietly dropped from an
 * invalidation is a panel that quietly goes stale.
 *
 * `part === null` is the blank canvas — no part is selected, so the
 * part-scoped keys have no argument to resolve against. The three
 * project-scoped keys still fire, and they are the ones that matter in exactly
 * that case: `keys.parts()` is how a part the agent has just created appears in
 * the tree.
 */
export function refreshKeys(part: string | null): readonly (readonly unknown[])[] {
  const projectScoped: readonly (readonly unknown[])[] = [
    keys.project(),
    keys.parts(),
    keys.gitStatus(),
  ];
  if (part === null) return projectScoped;
  return [
    ...projectScoped,
    keys.build(part),
    keys.script(part),
    keys.params(part),
    keys.properties(part),
    keys.checks(part),
    keys.dfm(part),
  ];
}

export function partNames(document: PartsDocument | undefined): readonly string[] {
  return document?.parts.map((row) => row.name) ?? [];
}

/**
 * §7A.11 (C7): the per-part build ref, keyed by name, from ONE server
 * projection. `GET /parts` already serves `content_hash` and `snapshot_ref`
 * per row; both are folded into the diffed value so a change to either marks
 * the row. The separator is U+0000, the same never-in-a-hash byte
 * `state/visibility.ts` uses.
 */
export function partRefs(document: PartsDocument | undefined): ReadonlyMap<string, string> {
  const refs = new Map<string, string>();
  for (const row of document?.parts ?? []) {
    refs.set(row.name, `${row.content_hash}\u0000${row.snapshot_ref}`);
  }
  return refs;
}

/**
 * Names whose build ref changed across the turn — created parts included,
 * removed parts not (there is no row left to mark). Both arguments are
 * `partRefs` of server projections, before-snapshot and after-fetch; nothing
 * here reads a tool result, and the answer carries no value — only names.
 */
export function changedPartNames(
  before: ReadonlyMap<string, string>,
  after: ReadonlyMap<string, string>,
): readonly string[] {
  const changed: string[] = [];
  for (const [name, ref] of after) {
    if (before.get(name) !== ref) changed.push(name);
  }
  return changed;
}

type Listener = () => void;

/**
 * §7A.11 (C7): which Parts-rail rows the LAST agent turn changed.
 *
 * The store is written by exactly one producer — `refreshAfterTurn`'s
 * two-projection diff — and cleared by exactly two things: the operator
 * clicking a marked row (`clear`), and the next turn's settle (`settle`, which
 * REPLACES the set with whatever that turn changed, so an empty diff clears
 * everything). History load, resync, pin movement, and re-renders never touch
 * it. The set is a marker, not a value: it says *this changed*, never what it
 * is now.
 */
class TurnChangedStore {
  #names: ReadonlySet<string> = new Set();
  readonly #listeners = new Set<Listener>();

  subscribe = (listener: Listener): (() => void) => {
    this.#listeners.add(listener);
    return () => {
      this.#listeners.delete(listener);
    };
  };

  getSnapshot = (): ReadonlySet<string> => this.#names;

  /** The next turn's settle: re-mark exactly what THAT turn changed. */
  settle(names: readonly string[]): void {
    if (names.length === 0 && this.#names.size === 0) return;
    this.#names = new Set(names);
    this.#emit();
  }

  /** The operator clicked the row: that row's marker, and only it, goes. */
  clear(name: string): void {
    if (!this.#names.has(name)) return;
    const next = new Set(this.#names);
    next.delete(name);
    this.#names = next;
    this.#emit();
  }

  #emit(): void {
    for (const listener of this.#listeners) listener();
  }
}

export const turnChangedStore = new TurnChangedStore();

/** Names in `after` that were not in `before` — both lists are server projections. */
export function createdPartNames(
  before: readonly string[],
  after: readonly string[],
): readonly string[] {
  const seen = new Set(before);
  return after.filter((name) => !seen.has(name));
}

/**
 * §4.5 amendment: select a part the agent just created, unless the pin is held.
 *
 * This writes `part`, never `artifact_ref` / `pin_mode`. `observeCurrent` still
 * owns the pin and still no-ops while held.
 */
export function adoptCreatedPart(store: WorkspaceStore, created: readonly string[]): void {
  if (created.length === 0) return;
  if (store.getSnapshot().pin_mode === "pinned") return;
  const name = created[created.length - 1];
  if (name === undefined || store.getSnapshot().part === name) return;
  store.update({ part: name, selection: null, measure: null });
}

/**
 * Invalidate the §7A.11 keys after one agent turn on this project.
 *
 * `invalidateQueries` marks the entry stale and refetches the **active**
 * observers; a panel nobody is looking at refetches when it next mounts. That
 * is the refetch-not-merge rule in its cheapest correct form — the new value is
 * always the server's answer to the same route the panel reads, never a value
 * this function computed.
 *
 * After the parts projection settles, adopt a name the tree did not have
 * unless the pin is held (§4.5's 2026-09-01 amendment). The pin doors are
 * not called here.
 *
 * Deliberately fire-and-forget: the caller has already rendered the turn, and a
 * composer that waited for nine refetches before re-enabling its textarea would
 * make the agent's own latency the operator's.
 */
export function refreshAfterTurn(client: QueryClient, part: string | null): void {
  const snapshot = client.getQueryData<PartsDocument>(keys.parts());
  const before = partNames(snapshot);
  const beforeRefs = partRefs(snapshot);
  for (const queryKey of refreshKeys(part)) {
    void client.invalidateQueries({ queryKey });
  }
  void client.invalidateQueries({ queryKey: keys.parts(), refetchType: "all" }).then(() => {
    const fetched = client.getQueryData<PartsDocument>(keys.parts());
    const after = partNames(fetched);
    // §7A.11 (C7): the same snapshot/diff, one more field — per-part build
    // refs. Two server projections across a refetch, never a tool result;
    // `settle` REPLACES the set, so this is also what clears last turn's marks.
    turnChangedStore.settle(changedPartNames(beforeRefs, partRefs(fetched)));
    adoptCreatedPart(workspaceStore, createdPartNames(before, after));
  });
}
