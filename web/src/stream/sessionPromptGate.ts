// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// Whether the current STREAM tab can take a prompt (INTERFACE.md §7A.2, §7A.5).
//
// RENAMED 2026-09-01 (§7.1(c)): `stream/sessionPrompt.ts` → this file.
// `stream/sessionPrompts.ts` — the store that remembers each session's opening
// line — keeps its name. Two modules in one directory differing only by a
// trailing `s`, one a gate and one a store, is a name that fails a reader on
// the import line. Mechanical: no exported symbol changed.
//
// §7A.2's create pair — New session / Ask about <part> — is reachable from
// exactly two explicit affordances. PR 1 already mounts them after the first
// session exists. This module is the *other* half of that table: the pair must
// also come back when the current tab cannot take a prompt, not only when
// `GET /sessions` is empty. A selected (now-dead) session that keeps the tabs
// and hides the pair is the dead-end #43 names.
//
// THE THREE WAYS A TAB CANNOT PROMPT, and they are not the same fact:
//
// * **runtime fault** — `data-runtime-fault` is set; the process is not
//   answering. Recovery is New session (`{profile: "orchestrator"}`).
// * **unknown_session** — the sidecar no longer has this id. That is a 4xx
//   about the *session*, not a runtime fault, and it still cannot take a
//   prompt.
// * **unavailable history** — the recorded transcript could not be read. The
//   tab is attached to something this page cannot speak through.
//
// `agent_unavailable` is deliberately **not** here. §7A.8 owns that refusal
// and its one action (re-read the config). Inventing a New session on a serve
// with no runtime would POST into the same 503.

import type { RuntimeFault } from "./runtimeFault";

export function sessionCannotPrompt(input: {
  readonly runtimeFault: RuntimeFault | null;
  readonly historyFailed: boolean;
  readonly streamReason: string | null;
}): boolean {
  if (input.runtimeFault !== null) return true;
  if (input.historyFailed) return true;
  return input.streamReason === "unknown_session";
}
