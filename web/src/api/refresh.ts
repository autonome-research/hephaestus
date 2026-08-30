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
// **2. The pin does not move.** §4.5's sticky-pin tightening (binding G5.6) is
// untouched: a refetch updates *current* and never re-points the workspace at a
// build the operator did not choose. This module never calls `workspaceStore`,
// and the one door a server response has to the pin — `observeCurrent` — is
// already a no-op while held.
//
// WHEN IT FIRES (§7A.11): on a `terminal` frame for a run on this project, and
// on the prompt response, which §7A.6 already makes the authority for turn
// completion. Both, not either: the response is the guarantee the originating
// tab gets, and the terminal frame is what an observer tab has.

import type { QueryClient } from "@tanstack/react-query";
import { keys } from "./queries";

/**
 * The keys §7A.11 enumerates, resolved for one part.
 *
 * Exported as data so the test asserts the **list** rather than the effect of
 * calling it: §7A.11 names these keys, and a key quietly dropped from an
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

/**
 * Invalidate the §7A.11 keys after one agent turn on this project.
 *
 * `invalidateQueries` marks the entry stale and refetches the **active**
 * observers; a panel nobody is looking at refetches when it next mounts. That
 * is the refetch-not-merge rule in its cheapest correct form — the new value is
 * always the server's answer to the same route the panel reads, never a value
 * this function computed.
 *
 * Deliberately fire-and-forget: the caller has already rendered the turn, and a
 * composer that waited for the refetches before re-enabling its textarea would
 * make the agent's own latency the operator's.
 */
export function refreshAfterTurn(client: QueryClient, part: string | null): void {
  for (const queryKey of refreshKeys(part)) {
    void client.invalidateQueries({ queryKey });
  }
}

/**
 * After a PARAMS slider write (§10).
 *
 * A rebuild dirties the same projections an agent turn does — Results, Checks,
 * DFM, properties, the script snapshot, the tree. Conflict is params-only:
 * nothing persisted and nothing rebuilt, so the other panels are still right.
 */
export function refreshAfterParamWrite(
  client: QueryClient,
  part: string,
  outcome: "rebuilt" | "conflict",
): void {
  if (outcome === "conflict") {
    void client.invalidateQueries({ queryKey: keys.params(part) });
    return;
  }
  refreshAfterTurn(client, part);
}
