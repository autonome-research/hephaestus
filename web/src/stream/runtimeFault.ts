// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The agent runtime died under a request (INTERFACE.md §7.4, §7A.5, §7A.8).
//
// THE STATE THE STREAM HEADER CANNOT CARRY. §7.4's vocabulary is closed at five
// values — `live`, `reconnecting`, `resyncing`, `historical`, `detached` — and
// every one of them is a claim about the SOCKET. None of them is a claim about
// the runtime behind it, and §23.7 records why the distinction is load-bearing:
// a credential change "restarts the sidecar" and "a restart kills every in-flight
// run in every session". The socket survives that (it reattaches to the fresh
// child); the run does not. So a page whose `session.prompt` and `history.page`
// have just failed under a restart is, in §7.4's terms, correctly `live` — and a
// header that says only `live` is telling the operator the one true thing that
// does not matter.
//
// Adding a sixth stream state was rejected: §7.4 closes that vocabulary, `4409`'s
// `resyncing` already means something else specific, and the e2e reads
// `data-stream-state` by name. This module produces a SEPARATE, independently
// addressable fact instead — `data-runtime-fault` — which the well states in its
// own words beside the socket state that remains true.
//
// WHAT THE CLIENT ACTUALLY KNOWS, and it is less than "the sidecar restarted".
// The supervisor fails an in-flight call with `{code: -32004, message: "sidecar
// restarted"}` and raises `SupervisorError`; `http/errors.py::refusal_for` has no
// branch for it, so the route answers **500 with no §2.4 envelope** and
// `api/client.ts` names that `transport_error`. This module therefore reports
// three grades and never rounds up to the reassuring or the alarming one:
//
//   `process_down`  the server named §2.4's own reason for a bridge that is not
//                   there. This is the restart, said by the server.
//   `timeout`       the server named the other bridge liveness terminal.
//   `unreachable`   a 5xx with no reason. The runtime is the only moving part
//                   behind these routes, so it is named as the likely cause and
//                   NOT asserted as the certain one.
//
// `agent_unavailable` is deliberately **not** here. §7A.8 owns that refusal, the
// composer already renders it with the server's cause and the config path it
// checked, and a second surface saying the same thing in different words is the
// defect §4.7's EmptyState rule ("a shared cause is detected once") names.

import { WorkspaceError } from "../api/client";

/** Closed, and each renders its own copy. Ordered most-specific first. */
export const RUNTIME_FAULTS = ["process_down", "timeout", "unreachable"] as const;
export type RuntimeFault = (typeof RUNTIME_FAULTS)[number];

/** §2.4 reasons that ARE this fault, by name. `PROTOCOL_CODE_REASON` in the engine. */
const NAMED: Readonly<Record<string, RuntimeFault>> = {
  process_down: "process_down",
  timeout: "timeout",
};

/**
 * The runtime fault one failed session request proves, or `null`.
 *
 * Total, and deliberately narrow. A 4xx is a refusal of the *request* and is
 * rendered as itself wherever it arrived; only a named liveness reason or an
 * unnamed 5xx on a session route says anything about the runtime's existence.
 */
export function runtimeFaultOf(error: unknown): RuntimeFault | null {
  if (!(error instanceof WorkspaceError)) return null;
  const named = NAMED[error.reason];
  if (named !== undefined) return named;
  // §7A.8's refusal is its own rendered state; see the module header.
  if (error.reason === "agent_unavailable") return null;
  return error.status >= 500 ? "unreachable" : null;
}
