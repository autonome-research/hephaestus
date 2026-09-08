// Concurrency isolation for the sidecar's per-run tool-invocation context.
//
// W5 goal (workflow handoff): a tool call's {sessionId, runId, invocation} is
// resolved by `resolveContext` (agent/src/main.ts) from whatever the currently
// executing run's context is. Two DIFFERENT sessions' turns are explicitly
// allowed to run at once — `BridgeRuntime._admit_turn`'s guard on the Python
// side refuses a second live turn on the SAME session but admits one on any
// OTHER session (INTERFACE.md §19.23: "a part session and the orchestrator may
// now think at the same time") — so two `session.prompt` RPC calls can be
// live on the SAME sidecar process at once, each one's tool calls interleaved
// with the other's on Node's single event loop.
//
// A single shared "current run" slot (the module-global `activeContext` this
// goal describes) cannot survive that: whichever run's handler assigned the
// slot LAST owns every tool call EITHER run makes for as long as both are
// live, and whichever run's `finally` clears the slot FIRST strands the other
// mid-turn. Both failures are silent identity failures — the wrong session id
// and entry id on a mutation's idempotency key, one run's `question`/`answer`
// events minted on another run's sequence, and "no active run for tool
// invocation" thrown at a tool call whose own run is very much still running.
//
// This is unreachable through `SessionService` directly (lifecycle.test.ts's
// fixture wires a hand-rolled custom tool that never calls `resolveContext`),
// so this file drives the REAL production entry module (`src/main.ts`) — its
// module-level `activeRuns`/`runScope` state, its `registerHandlers`-bound
// handler table, everything `heph-agent` actually runs — standing in for BOTH
// the supervisor (session.create/session.prompt) and the Python bridge
// (py.tool_dispatch, py.ask_user) ourselves. The fake model is `FakeModel`
// (session/runtime.ts), a real HTTP server the child process's own
// `runtime.configure` points at — nothing here talks to a real provider.
//
// Two sessions prompt at once: "part" needs three model round trips
// (read_part, then ask_user, then a final text) and "orchestrator" needs two
// (read_part, then a final text). Rather than hope OS/event-loop scheduling
// happens to interleave them, this test FORCES a genuine overlap: standing in
// for Python, it holds orchestrator's `read_part` dispatch response pending
// until part's `ask_user` request has actually arrived, so for that window
// BOTH runs are simultaneously suspended mid-turn on this same process —
// exactly the condition a shared "current run" slot cannot survive, and
// exactly the condition a per-run context (an `AsyncLocalStorage` scope, or
// equivalent) is designed to. A correct per-run fix makes every assertion
// below true regardless of which turn happens to finish first.
//
// audit-2026-09-04 J-mirrors-and-dx-31 landed the seam this file now uses:
// `src/main.ts` used to construct its peer and register all seventeen
// handlers as MODULE-LEVEL side effects, so it "cannot be imported" — the
// only way to drive it was to compile the whole source tree with `tsc` and
// spawn the emitted `main.js` as a child process, which is what this file did
// until this round (a ~10s build on every run, the only file in the suite
// that paid it). `registerHandlers(peer)` now binds that same table — the
// exact production handlers, including the `activeRuns`/`runScope` state this
// test exists to exercise — to any `RpcPeer`, so two `RpcPeer`s wired directly
// to each other in-process reproduce the real two-sided protocol with no
// compiled `dist/` tree and no subprocess. This is not a weaker substitute for
// the child-process version: it is literally the same module (`src/main.ts`,
// transpiled on the fly by Vitest rather than by `tsc`), so a defect in
// per-run scoping is exactly as reachable here as it was over real stdio.

import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import type { JsonValue } from "../../src/framing.js";
import { RpcPeer } from "../../src/rpc.js";
import { FakeModel, type FakeRequestInfo, type FakeTurn, type FakeTurnResolver } from "../../src/session/runtime.js";

// -- profile system-prompt markers (session/profiles.ts PROFILE_PROMPT_NOTE) --
// Distinctive substrings of each profile's system prompt, used to tell the two
// sessions' model requests apart (FakeModel's script is one shared cursor
// consumed by BOTH sessions' HTTP calls in arrival order, so the resolver must
// identify the session from the request body itself rather than from turn
// position — session/runtime.ts's FakeModel mirrors fake_openai.py exactly
// this way).
const PART_MARKER = "You own exactly one part.";
const ORCH_MARKER = "You are the project orchestrator.";

interface RecordedDispatch {
  readonly sessionId: string;
  readonly runId: string;
  readonly tool: string;
  readonly args: { readonly [k: string]: JsonValue };
}

interface RecordedEvent {
  readonly runId: string;
  readonly kind: string;
  readonly seq: number;
}

interface RecordedQuestion {
  readonly runId: string;
}

/**
 * Two `RpcPeer`s wired directly to each other in-process, standing in for the
 * stdio pipe between the Python supervisor and the sidecar. `sidecarPeer` is
 * bound to `src/main.ts`'s real handler table via `registerHandlers`; `peer`
 * plays the Python side of the protocol the way `BridgeRuntime` does —
 * answering `py.tool_dispatch` / `py.ask_user`, recording `event` /
 * `terminal` notifications.
 *
 * Each side's `sink` feeds the other's `handleFrame` directly with the JSON
 * bytes `handleFrame` itself expects (`main_wiring.test.ts` drives a single
 * peer the same way). There is no framed byte stream to encode/decode here —
 * that machinery (`framing.ts`'s `encodeFrame`/`FrameDecoder`) exists for a
 * real OS pipe, and this harness has none.
 */
class SidecarHarness {
  readonly peer: RpcPeer;
  readonly toolDispatches: RecordedDispatch[] = [];
  readonly questions: RecordedQuestion[] = [];
  readonly answers: RecordedQuestion[] = [];
  readonly events: RecordedEvent[] = [];
  /** Set when a tool result embeds the "no active run for tool invocation" fault. */
  sawNoActiveRunError = false;
  /**
   * Deterministic-overlap hook: called synchronously as each `py.tool_dispatch`
   * arrives, before the stub result is returned. Returning a promise HOLDS that
   * dispatch's response until it settles — the mechanism the test uses to force
   * two sessions' runs to be genuinely, simultaneously suspended mid-turn on
   * this one process, rather than hoping scheduling happens to do it.
   */
  onToolDispatch?: (call: RecordedDispatch) => Promise<void> | void;
  /** Called synchronously as each `py.ask_user` request arrives. */
  onAskUser?: (runId: string) => void;

  private readonly sidecarPeer: RpcPeer;

  constructor(registerHandlers: (target: RpcPeer) => void) {
    // Each side's sink closure reaches the other through `this.sidecarPeer` /
    // `this.peer` rather than a local variable: the closures aren't INVOKED
    // until a later `request`/`notify`, by which point both fields are
    // assigned, so the forward reference is safe despite `sidecarPeer` not
    // existing yet at the moment `this.peer`'s constructor body runs.
    this.peer = new RpcPeer((frame) => {
      void this.sidecarPeer.handleFrame(Buffer.from(JSON.stringify(frame)));
    });
    this.sidecarPeer = new RpcPeer((frame) => {
      void this.peer.handleFrame(Buffer.from(JSON.stringify(frame)));
    });
    registerHandlers(this.sidecarPeer);

    // Stand in for `hephaestus.agent_bridge.dispatch.ToolDispatcher`: record
    // exactly what the sidecar attributed the call to, and return a minimal
    // `read_part` result that satisfies `readPartResult`'s required fields
    // (schema.gen.ts) so the tool loop can continue either way.
    this.peer.on("py.tool_dispatch", async (params) => {
      const args = (params.arguments ?? {}) as { readonly [k: string]: JsonValue };
      const call: RecordedDispatch = {
        sessionId: String(params.session_id ?? ""),
        runId: String(params.run_id ?? ""),
        tool: String(params.tool ?? ""),
        args,
      };
      this.toolDispatches.push(call);
      await this.onToolDispatch?.(call);
      return {
        script: "# stub",
        content_hash: "stub-hash",
        snapshot_ref: "artifact:stub-snapshot",
        truncated: false,
      };
    });
    // Stand in for the human: answer immediately, recording the `run_id`
    // main.ts's `py.ask_user` bracket resolved it to (the sharpest place a
    // wrong run id shows up — see the file banner).
    this.peer.on("py.ask_user", (params) => {
      const runId = String(params.run_id ?? "");
      this.questions.push({ runId });
      this.onAskUser?.(runId);
      return { selection: "6 mm plywood" };
    });

    this.peer.onNotify("event", (params) => {
      this.events.push({
        runId: String(params.run_id ?? ""),
        kind: String(params.kind ?? ""),
        seq: Number(params.seq ?? -1),
      });
      if (params.kind === "answer") this.answers.push({ runId: String(params.run_id ?? "") });
    });
    this.peer.onNotify("terminal", () => {});
  }

  async configure(providerSpec: JsonValue): Promise<void> {
    await this.peer.request("runtime.configure", { providers: [providerSpec] });
  }

  async createSession(profile: string, sessionId: string, projectRoot: string, part?: string): Promise<void> {
    const params: { [k: string]: JsonValue } = {
      profile,
      project_root: projectRoot,
      session_id: sessionId,
    };
    if (part !== undefined) params.part = part;
    await this.peer.request("session.create", params);
  }

  prompt(sessionId: string, runId: string, promptText: string): Promise<JsonValue> {
    return this.peer.request(
      "session.prompt",
      { session_id: sessionId, run_id: runId, prompt: promptText },
      120_000,
    );
  }
}

function toolCallsTurn(name: string, args: Record<string, unknown>, id: string): FakeTurn {
  return { kind: "tool_calls", calls: [{ name, arguments: args, id }] };
}

function textTurn(...chunks: string[]): FakeTurn {
  return { kind: "text", chunks };
}

let fake: FakeModel;
let harness: SidecarHarness;
let agentDataDir: string;
let projectRoot: string;
let sawProcessFault = false;

function onProcessFault(reason: unknown): void {
  sawProcessFault = true;
  console.error("[concurrency.test] unhandled rejection/exception while both runs were in flight", reason);
}

beforeAll(async () => {
  agentDataDir = mkdtempSync(path.join(tmpdir(), "heph-conc-agent-"));
  projectRoot = mkdtempSync(path.join(tmpdir(), "heph-conc-proj-"));
  // `src/main.ts`'s `agentDir` is read once, at module load — the equivalent
  // of the env var the old spawned-child version passed to the subprocess —
  // so it must be set before the dynamic import below.
  process.env.HEPHAESTUS_AGENT_DIR = agentDataDir;
  process.on("unhandledRejection", onProcessFault);
  process.on("uncaughtException", onProcessFault);

  const mainModule = await import("../../src/main.js");
  fake = await FakeModel.start([]);
  harness = new SidecarHarness(mainModule.registerHandlers);
  await harness.configure(fake.providerSpec() as unknown as JsonValue);
}, 60_000);

afterAll(async () => {
  process.off("unhandledRejection", onProcessFault);
  process.off("uncaughtException", onProcessFault);
  await fake?.close();
  rmSync(agentDataDir, { recursive: true, force: true });
  rmSync(projectRoot, { recursive: true, force: true });
});

describe("concurrent session.prompt calls do not clobber the sidecar's active-run context", () => {
  it("scopes tool dispatch, ask_user, and events to the session that produced them", async () => {
    const PART_SESSION = "sess-conc-part";
    const ORCH_SESSION = "sess-conc-orch";
    const PART_RUN = "run-conc-part";
    const ORCH_RUN = "run-conc-orch";

    await harness.createSession("part", PART_SESSION, projectRoot, "widget_a");
    await harness.createSession("orchestrator", ORCH_SESSION, projectRoot);

    // Shared script cursor (session/runtime.ts's FakeModel, like the Python
    // fake_openai.py it mirrors): every resolver call must identify its own
    // session from the request body rather than from turn position.
    const resolver: FakeTurnResolver = (req: FakeRequestInfo) => {
      const isPart = req.bodyText.includes(PART_MARKER);
      const isOrch = req.bodyText.includes(ORCH_MARKER);
      if (isPart === isOrch) {
        throw new Error("resolver could not tell the two sessions' requests apart");
      }
      const toolResultCount = req.roles.filter((r) => r === "tool").length;
      if (toolResultCount > 0 && req.bodyText.includes("no active run for tool invocation")) {
        harness.sawNoActiveRunError = true;
      }
      if (isOrch) {
        if (toolResultCount === 0) return toolCallsTurn("read_part", { name: "widget_b" }, "orch-read");
        return textTurn("ORCH_DONE");
      }
      // part: read_part, then ask_user, then done — deliberately one round
      // trip longer than orchestrator's (see file banner).
      if (toolResultCount === 0) return toolCallsTurn("read_part", { name: "widget_a" }, "part-read");
      if (toolResultCount === 1) {
        return toolCallsTurn("ask_user", { question: "which stock?", options: ["a", "b"] }, "part-ask");
      }
      return textTurn("PART_DONE");
    };
    fake.setScript(Array.from({ length: 12 }, () => resolver));

    // Force the overlap deterministically (file banner): hold orchestrator's
    // `read_part` dispatch open until part's `ask_user` request has actually
    // arrived, so for that window both runs are simultaneously suspended
    // mid-turn — orchestrator inside its `py.tool_dispatch` await, part inside
    // its `py.ask_user` await — on this one sidecar process.
    let releasePartAskUserSeen!: () => void;
    const partAskUserSeen = new Promise<void>((resolve) => {
      releasePartAskUserSeen = resolve;
    });
    harness.onAskUser = (runId) => {
      if (runId === PART_RUN) releasePartAskUserSeen();
    };
    harness.onToolDispatch = async (call) => {
      if (call.sessionId === ORCH_SESSION) await partAskUserSeen;
    };

    // Fired concurrently, neither awaited before the other starts — this is
    // the condition the file banner's forced overlap depends on.
    const [partResult, orchResult] = await Promise.all([
      harness.prompt(PART_SESSION, PART_RUN, "read the part then ask about stock"),
      harness.prompt(ORCH_SESSION, ORCH_RUN, "read the part"),
    ]);

    expect((partResult as { status?: string }).status).toBe("completed");
    expect((orchResult as { status?: string }).status).toBe("completed");

    // -- (1) every emitted event names the run that actually produced it ----
    const validRunIds = new Set([PART_RUN, ORCH_RUN]);
    for (const ev of harness.events) {
      expect(validRunIds.has(ev.runId), `event ${ev.kind} carried an unknown run_id ${ev.runId}`).toBe(true);
    }
    // Only the part turn calls ask_user — its question/answer pair is the one
    // path (main.ts's py.ask_user bracket) that reads `activeContext.runId`
    // directly rather than through the normalizeLiveEvent closure, so it is
    // the sharpest place a wrong run id would show up.
    const questionEvents = harness.events.filter((e) => e.kind === "question" || e.kind === "answer");
    expect(questionEvents.length).toBeGreaterThan(0);
    for (const ev of questionEvents) {
      expect(ev.runId, `${ev.kind} event mis-scoped to run ${ev.runId}, expected the part turn's ${PART_RUN}`).toBe(
        PART_RUN,
      );
    }

    // -- (2) no invocation ever raced `activeContext` to undefined ----------
    expect(
      harness.sawNoActiveRunError,
      '"no active run for tool invocation" leaked into a tool result — activeContext was cleared out from under a still-running turn',
    ).toBe(false);

    // -- (3) every tool dispatch carries the session that issued it ---------
    expect(harness.toolDispatches.length).toBeGreaterThanOrEqual(2);
    for (const call of harness.toolDispatches) {
      const expectedSession = call.args.name === "widget_a" ? PART_SESSION : ORCH_SESSION;
      const expectedRun = call.args.name === "widget_a" ? PART_RUN : ORCH_RUN;
      expect(
        call.sessionId,
        `py.tool_dispatch for ${JSON.stringify(call.args)} carried session ${call.sessionId}, expected ${expectedSession}`,
      ).toBe(expectedSession);
      expect(call.runId).toBe(expectedRun);
    }

    // -- (4) no fault leaked out of process while both runs were in flight --
    expect(
      sawProcessFault,
      "an unhandled rejection or uncaught exception surfaced while both runs were concurrently in flight",
    ).toBe(false);
  }, 90_000);
});
