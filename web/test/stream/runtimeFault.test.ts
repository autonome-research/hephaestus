// Copyright 2026 The Hephaestus Authors
// SPDX-License-Identifier: Apache-2.0
//
// The runtime died and the well says so (INTERFACE.md §7.4, §7A.8, §23.7).
//
// THE DEFECT THESE ASSERTIONS PIN. A credential-driven sidecar restart killed a
// run mid-turn; `history.page` and `session.prompt` both failed under it. The
// well went on showing `✓ live` and never named the restart, because §7.4's five
// states are all claims about the SOCKET and the socket had genuinely
// reattached. The header was stating the one true thing that did not matter.
//
// The assertions are about the CLASSIFICATION, not the copy: which failures are
// evidence about the runtime's existence, which are evidence about the request,
// and which belong to a surface that already owns them.

import { describe, expect, it } from "vitest";
import { WorkspaceError } from "../../src/api/client";
import { RUNTIME_FAULTS, runtimeFaultOf } from "../../src/stream/runtimeFault";

describe("what counts as evidence that the runtime is not answering", () => {
  it("takes the server's own liveness reasons by name", () => {
    // `PROTOCOL_CODE_REASON` in `http/errors.py`: the engine carries a dead
    // bridge as a numeric JSON-RPC code and these are its two reason strings.
    expect(runtimeFaultOf(new WorkspaceError(503, "process_down", "sidecar restarted"))).toBe(
      "process_down",
    );
    expect(runtimeFaultOf(new WorkspaceError(504, "timeout", "no response"))).toBe("timeout");
  });

  it("reports an unnamed 5xx as unreachable, not as a restart it cannot see", () => {
    // What actually happens today: `SupervisorError` has no branch in
    // `refusal_for`, so the route answers 500 with no §2.4 envelope and
    // `api/client.ts` names that `transport_error`. The runtime is the only
    // moving part behind these routes, so it is named as the likely cause —
    // and the grade is distinct, because the server did not say so.
    expect(runtimeFaultOf(new WorkspaceError(500, "transport_error", "HTTP 500"))).toBe(
      "unreachable",
    );
    expect(runtimeFaultOf(new WorkspaceError(502, "transport_error", "HTTP 502"))).toBe(
      "unreachable",
    );
  });

  it("leaves agent_unavailable to §7A.8, which renders it with a cause and a path", () => {
    // §4.7's second EmptyState rule: a shared cause is detected once. The
    // composer already names this refusal, the server's closed `cause` and the
    // config path it checked; a band saying it again in other words is two
    // answers to one question.
    expect(
      runtimeFaultOf(new WorkspaceError(503, "agent_unavailable", "no runtime attached")),
    ).toBeNull();
  });

  it("says nothing about the runtime when the REQUEST was refused", () => {
    // A 4xx is an answer about what was asked, and each of these is rendered as
    // itself where it arrived. Rounding them up to "the runtime is gone" would
    // put a red band over a working session.
    for (const [status, reason] of [
      [400, "invalid_params"],
      [404, "unknown_session"],
      [409, "run_in_flight"],
      [409, "session_busy"],
      [429, "busy"],
    ] as const) {
      expect(runtimeFaultOf(new WorkspaceError(status, reason, reason)), reason).toBeNull();
    }
  });

  it("is total, and says nothing about a failure it cannot read", () => {
    // A lost POST is not a `WorkspaceError` at all: §7A.5 renders that as
    // `data-send-state="unknown"` and names the stream as the authority, which
    // is a weaker claim than this function is allowed to make.
    expect(runtimeFaultOf(new Error("network"))).toBeNull();
    expect(runtimeFaultOf(null)).toBeNull();
    expect(runtimeFaultOf(undefined)).toBeNull();
    expect(runtimeFaultOf("sidecar restarted")).toBeNull();
  });

  it("only ever answers from the closed set", () => {
    const answers = [
      runtimeFaultOf(new WorkspaceError(503, "process_down", "x")),
      runtimeFaultOf(new WorkspaceError(504, "timeout", "x")),
      runtimeFaultOf(new WorkspaceError(500, "transport_error", "x")),
    ];
    for (const answer of answers) expect(RUNTIME_FAULTS).toContain(answer);
  });
});
