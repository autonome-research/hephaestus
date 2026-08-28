// Hephaestus Pi sidecar entry point — the full Stage 2A runtime loop.
//
// stdout carries ONLY protocol frames; all logging goes to stderr. The sidecar
// is the SERVER for session.*/history.*/query.*/runtime.* requests the Python
// supervisor sends, and the CLIENT for the py.* requests its tool proxy
// originates (py.tool_dispatch / py.ask_user / py.delegate / …).
//
// Wiring (DESIGN.md "Wire protocol", STAGE2_DIGEST §1/§5/§6):
//   runtime.configure  -> build the app-owned ModelRuntime + one SessionService
//   session.create     -> SessionService.create (part / orchestrator / quick_edit)
//   session.prompt     -> begin a run, stream normalized events, emit a terminal
//   session.cancel     -> abort only that run's stream + tool children
//   session.compact    -> Pi compaction with a pinned CAD summary
//   history.page       -> normalized, high-water-frozen historical read
//   query.snapshot     -> ephemeral toolless single-turn vision child
//
// Tool calls flow model -> ToolProxy -> peer.request(py.tool_dispatch|…) -> Python
// core and back; inspect images ride inline within the §5 budgets. ask_user is a
// blocking py.ask_user request whose response is the human selection.
//
// FakeModel is test-only and is NEVER started here — production models arrive
// through runtime.configure.

import process from "node:process";
import { FrameDecoder, encodeFrame, FrameTooLargeError } from "./framing.js";
import type { JsonValue } from "./framing.js";
import { RpcPeer, RpcError, ErrorCode, FRAME_VERSION } from "./rpc.js";
import type { ModelRuntime } from "@earendil-works/pi-coding-agent";
import { createModelRuntime, type RuntimeConfig, type PiModel } from "./session/runtime.js";
import { SessionService, type ManagedSession } from "./session/manager.js";
import type { SessionProfile } from "./session/profiles.js";
import { pageHistory } from "./session/history.js";
import { normalizeLiveEvent, wireEvent } from "./session/live.js";
import {
  ContextPolicy,
  formatPinnedSummary,
  type PinnedCadSummary,
} from "./session/context.js";
import { promptWithTransientRetry, turnErrorOf } from "./session/retry.js";
import { ToolProxy, type ProxyContext } from "./tools/proxy.js";
import { buildAllTools } from "./tools/registry.js";
import { InvocationTracker, type TrustedInvocation } from "./tools/invocation.js";
import type { HephaestusEvent } from "./events.js";

function log(message: string): void {
  process.stderr.write(`[heph-sidecar] ${message}\n`);
}

const peer = new RpcPeer((frame) => {
  process.stdout.write(encodeFrame(frame));
});

// ── active-run tool-invocation context ───────────────────────────────────────
// One prompt runs per session at a time; tool `execute` fires synchronously
// within the awaited prompt, so a single "current context" resolves the trusted
// invocation for the tool proxy. Concurrent prompts in the tests never execute
// tools, so clobbering is harmless.
interface ActiveContext {
  readonly sessionId: string;
  readonly runId: string;
  readonly tracker: InvocationTracker;
  /** Run-monotonic event sequence shared by live + synthetic events. */
  readonly nextSeq: () => number;
  /** Whether this session's model can read image blocks (arch §4.1 capability). */
  readonly imagesSupported: boolean;
  ordinal: number;
}
let activeContext: ActiveContext | undefined;

/** Emit one normalized event frame on the private bridge (stdout, never logs). */
function emitEvent(ev: HephaestusEvent): void {
  peer.notify("event", wireEvent(ev));
}

function resolveContext(toolCallId: string): ProxyContext {
  const active = activeContext;
  if (active === undefined) {
    throw new RpcError(ErrorCode.INTERNAL_ERROR, "no active run for tool invocation");
  }
  const ordinal = active.ordinal;
  active.ordinal += 1;
  const invocation: TrustedInvocation = active.tracker.register({
    sessionId: active.sessionId,
    // A run-scoped, monotonic entry id keeps every attempt id unique and stable
    // within the run (a full retry-stable persisted entry id lands with the
    // delegation coordinator).
    entryId: `${active.runId}#${ordinal}`,
    ordinal,
    providerCallId: toolCallId,
  });
  return {
    sessionId: active.sessionId,
    runId: active.runId,
    invocation,
    imagesSupported: active.imagesSupported,
  };
}

// The proxy's bridge transport is the peer's client-request path back to Python.
// `py.ask_user` is a *suspension*: the model's turn blocks until a human answers,
// so it is bracketed with the public `question` / `answer` events (never dropped,
// never coalesced) before the raw request crosses the bridge.
//
// INTERFACE.md §2.7 ("`ask_user` with two clients attached"): the question
// broadcasts to EVERY attached client and the answer is idempotent on the
// **question id**, first answer wins. That id did not exist — the `question`
// event carried only `{question, options}`, so a client that saw one had nothing
// to answer *with*. It is minted here, at the one place that brackets the
// suspension, and travels three ways at once: in the `question` event's payload
// (so any client can answer), in the `py.ask_user` params (so Python can match
// an answer to the pending question), and in the `answer` event's payload (so
// every other attached client can disable its widget). No event kind is minted
// and no field is added to `HephaestusEvent`; this is payload content only.
let questionOrdinal = 0;
const proxy = new ToolProxy(async (method, params) => {
  if (method !== "py.ask_user") return peer.request(method, params);
  const active = activeContext;
  const runId = active?.runId ?? String(params.run_id ?? "");
  const questionId = `q-${runId}-${questionOrdinal++}`;
  if (active !== undefined) {
    emitEvent({
      runId,
      seq: active.nextSeq(),
      kind: "question",
      payload: {
        question_id: questionId,
        question: params.question ?? null,
        options: params.options ?? [],
      },
    });
  }
  // No client-side timeout: the question stays open until the operator answers
  // (Python owns the interaction deadline).
  const answer = await peer.request(method, { ...params, question_id: questionId }, 0);
  if (active !== undefined) {
    emitEvent({
      runId,
      seq: active.nextSeq(),
      kind: "answer",
      payload: { question_id: questionId, answer },
    });
  }
  return answer;
});
const customTools = buildAllTools({ proxy, resolveContext });

// ── runtime + session service (built at runtime.configure) ───────────────────
let runtime: ModelRuntime | undefined;
let service: SessionService | undefined;
const agentDir = process.env.HEPHAESTUS_AGENT_DIR ?? process.cwd();

function requireService(): SessionService {
  if (service === undefined) {
    throw new RpcError(ErrorCode.INVALID_REQUEST, "runtime.configure has not run yet");
  }
  return service;
}

function firstModel(rt: ModelRuntime, config: RuntimeConfig): PiModel {
  for (const provider of config.providers) {
    for (const model of provider.models) {
      const resolved = rt.getModel(provider.id, model.id);
      if (resolved) return resolved;
    }
  }
  throw new RpcError(ErrorCode.INVALID_PARAMS, "runtime.configure resolved no model");
}

peer.on("runtime.configure", async (params) => {
  const config = params as unknown as RuntimeConfig;
  runtime = await createModelRuntime(config, { agentDir });
  const model = firstModel(runtime, config);
  service = new SessionService({ runtime, agentDir, model, customTools });
  log(`configured runtime: ${config.providers.length} provider(s)`);
  return { ok: true, providers: config.providers.length };
});

peer.on("session.create", async (params) => {
  const svc = requireService();
  const profile = String(params.profile) as SessionProfile;
  const projectRoot = String(params.project_root);
  const request = {
    profile,
    projectRoot,
    ...(params.session_id !== undefined ? { sessionId: String(params.session_id) } : {}),
    ...(params.part !== undefined && params.part !== null ? { part: String(params.part) } : {}),
    ...(params.resume === true ? { resume: true } : {}),
  };
  const managed =
    request.resume === true ? await svc.resume(request) : await svc.create(request);
  return { session_id: managed.id, profile: managed.profile, part: managed.part ?? null };
});

function stubSummary(managed: ManagedSession): PinnedCadSummary {
  return {
    designIntent: `session ${managed.id} (${managed.profile})`,
    decisions: [],
    openProblems: [],
    params: {},
    checkStatus: "unknown",
  };
}

peer.on("session.prompt", async (params) => {
  const svc = requireService();
  const sessionId = String(params.session_id);
  const runId = String(params.run_id);
  const promptText = String(params.prompt);
  const managed = svc.get(sessionId);
  if (managed === undefined) {
    throw new RpcError(ErrorCode.INVALID_PARAMS, `unknown session '${sessionId}'`);
  }

  const controller = svc.beginRun(sessionId, runId);
  let seq = 0;
  const next = (): number => seq++;
  const policy = new ContextPolicy({ summary: () => stubSummary(managed) });

  // Live normalization: Pi streaming events become public Hephaestus events as
  // they happen, on the same run-monotonic sequence as the synthetic ones.
  //
  // An assistant turn that ERRORS (provider/auth/stream failure) does not make
  // `session.prompt` reject — Pi records stopReason "error" on the persisted
  // message and resolves. Without watching for it the run reported `completed`
  // with zero events, which is how 15 live runs silently no-opped on
  // 2026-08-02 while the real cause ("OAuth auth derivation failed") sat
  // unread in the session file. An errored turn is a FAILED run, loudly —
  // except that a NAMED transient provider fault gets exactly one automatic
  // retry (session/retry.ts; EXTERNAL_EVAL.md §5: the fault is uncharged, the
  // retry turn's tool calls are charged normally).
  let turnError: string | undefined;
  const unsubscribe = managed.session.subscribe((ev) => {
    const errored = turnErrorOf(ev);
    if (errored !== undefined) turnError = errored;
    for (const normalized of normalizeLiveEvent(ev, runId, next)) {
      emitEvent(normalized);
    }
  });

  activeContext = {
    sessionId,
    runId,
    tracker: new InvocationTracker(),
    nextSeq: next,
    imagesSupported: managed.model.input.includes("image"),
    ordinal: 0,
  };
  let state: "completed" | "cancelled" | "failed" = "completed";
  let errorMessage: string | undefined;
  try {
    const outcome = await promptWithTransientRetry(promptText, {
      prompt: (text) => managed.session.prompt(text),
      takeTurnError: () => {
        const captured = turnError;
        turnError = undefined;
        return captured;
      },
      aborted: () => controller.signal.aborted,
      onRetry: (message, transientClass) => {
        // The archive shows the fault and the single retry (audit events are
        // never coalesced or dropped).
        emitEvent({
          runId,
          seq: next(),
          kind: "audit",
          payload: { event: "turn_retry", error: message, transient_class: transientClass },
        });
      },
    });
    state = outcome.state;
    if (outcome.errorMessage !== undefined) errorMessage = outcome.errorMessage;
    // Drive the context policy off post-turn usage (compaction/escalation).
    await applyContextPolicy(managed, runId, policy);
  } catch (err) {
    if (controller.signal.aborted) {
      state = "cancelled";
    } else {
      state = "failed";
      errorMessage = err instanceof Error ? err.message : String(err);
    }
  } finally {
    unsubscribe();
    activeContext = undefined;
    svc.endRun(runId);
  }

  const terminalPayload: { [k: string]: JsonValue } =
    errorMessage !== undefined ? { error: errorMessage } : {};
  peer.notify("terminal", {
    run_id: runId,
    terminal_id: `terminal:${runId}`,
    state,
    payload: terminalPayload,
  });
  return { status: state, run_id: runId };
});

async function applyContextPolicy(
  managed: ManagedSession,
  runId: string,
  policy: ContextPolicy,
): Promise<void> {
  const usage = managed.session.getContextUsage();
  const fraction = usage?.percent != null ? usage.percent / 100 : null;
  for (const action of policy.evaluate(fraction)) {
    if (action.kind === "compact") {
      await managed.session.compact(action.instructions);
      policy.reset();
      emitEvent({
        runId,
        seq: activeContext?.nextSeq() ?? 0,
        kind: "audit",
        payload: { event: "compaction", trigger: "threshold" },
      });
    } else {
      // Budget escalation: surface a question to the operator via py.ask_user.
      await peer.request("py.ask_user", {
        run_id: runId,
        question: `Context budget at ${Math.round(action.percent * 100)}%. Continue?`,
        options: ["continue", "stop"],
        allow_free_text: false,
        multi: false,
      });
    }
  }
}

peer.on("session.cancel", async (params) => {
  const svc = requireService();
  const runId = String(params.run_id);
  await svc.cancel(runId);
  return { ok: true, run_id: runId };
});

peer.onNotify("cancel", (params) => {
  const svc = service;
  if (svc === undefined) return;
  void svc.cancel(String(params.run_id));
});

peer.on("session.compact", async (params) => {
  const svc = requireService();
  const sessionId = String(params.session_id);
  const managed = svc.get(sessionId);
  if (managed === undefined) {
    throw new RpcError(ErrorCode.INVALID_PARAMS, `unknown session '${sessionId}'`);
  }
  const instructions = formatPinnedSummary(stubSummary(managed));
  const result = await managed.session.compact(instructions);
  return { summary: result.summary ?? "" };
});

peer.on("history.page", (params) => {
  const svc = requireService();
  const sessionId = String(params.session_id);
  const managed = svc.get(sessionId);
  if (managed === undefined) {
    throw new RpcError(ErrorCode.INVALID_PARAMS, `unknown session '${sessionId}'`);
  }
  const entries = managed.session.sessionManager.getEntries();
  const page = pageHistory(
    entries,
    sessionId,
    params.cursor !== undefined ? { cursor: String(params.cursor) } : {},
  );
  return {
    events: page.events.map(wireEvent),
    cursor: page.cursor,
    done: page.done,
  };
});

peer.on("query.snapshot", async (params) => {
  const svc = requireService();
  const runId = String(params.run_id);
  const question = String(params.question);
  const managed = await svc.create({
    profile: "query_snapshot",
    projectRoot: agentDir,
    sessionId: `qs-${runId}`,
  });
  try {
    await managed.session.prompt(question);
    const answer = managed.session.getLastAssistantText() ?? "";
    return { status: "ok", answer };
  } finally {
    await svc.dispose(managed.id);
  }
});

peer.on("shutdown", () => {
  log("shutdown requested");
  queueMicrotask(() => {
    void service?.disposeAll().finally(() => process.exit(0));
  });
  return { ok: true };
});

const decoder = new FrameDecoder();

process.stdin.on("data", (chunk: Buffer) => {
  let frames: Buffer[];
  try {
    frames = decoder.push(chunk);
  } catch (err) {
    if (err instanceof FrameTooLargeError) {
      log(`fatal framing error: ${err.message}`);
    } else {
      log(`fatal framing error: ${String(err)}`);
    }
    process.exit(1);
    return;
  }
  for (const frame of frames) {
    void peer.handleFrame(frame);
  }
});

process.stdin.on("end", () => {
  process.exit(0);
});

log(`started pid=${process.pid} hv=${FRAME_VERSION}`);
