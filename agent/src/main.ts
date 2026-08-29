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
import {
  createModelRuntime,
  type ProviderAvailability,
  type RuntimeConfig,
  type PiModel,
} from "./session/runtime.js";
import {
  CredentialError,
  LoginFlows,
  lastObserved,
  observeTurn,
  reduceLoginError,
  type FlowProjection,
} from "./session/credentials.js";
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
//
// `allow_free_text` and `multi` ride along for the same reason and under the
// same rule. INTERFACE.md §7A.7 makes the answering affordance a function of
// the question's own params — "options with `multi:false` → one button per
// option plus a free-text field **only if** `allow_free_text`" — and states that
// the `question` payload carries them. It did not: the payload was
// `{question_id, question, options}`, so every client that answers from the
// event alone (the web widget, and `heph agent` in §2.1 client mode, which
// reads this payload rather than the tool params) had to assume the schema
// defaults. Assuming `allow_free_text: true` on a question that declared it
// `false` offers an answer the tool's own schema does not admit, which §7A.7
// forbids outright — so the two fields are carried instead of guessed.
// `?? null` is not used on them: the schema's defaults are `true` and `false`
// (`schemas/tools/ask_user.schema.json`), a client reads an absent field as
// that default, and writing `null` would put a third value on the wire.
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
        allow_free_text: params.allow_free_text !== false,
        multi: params.multi === true,
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
let availability: readonly ProviderAvailability[] = [];
const logins = new LoginFlows();
const agentDir = process.env.HEPHAESTUS_AGENT_DIR ?? process.cwd();

function requireService(): SessionService {
  if (service === undefined) {
    // INTERFACE.md §23.7: with per-provider verification, "no service" now has
    // two distinct causes and they must not read as one. A runtime that was
    // never configured is the old message. A runtime that WAS configured but
    // whose every provider failed verification refuses with **that provider's
    // own code** — never with a generic one, and never by falling back to a
    // provider that did verify, because there is none.
    const failed = availability.find((entry) => !entry.available);
    if (failed !== undefined) {
      throw new RpcError(ErrorCode.INVALID_REQUEST, failed.unavailable_reason ?? "provider_unknown");
    }
    throw new RpcError(ErrorCode.INVALID_REQUEST, "runtime.configure has not run yet");
  }
  return service;
}

function requireRuntime(): ModelRuntime {
  if (runtime === undefined) {
    throw new RpcError(ErrorCode.INVALID_REQUEST, "runtime.configure has not run yet");
  }
  return runtime;
}

/**
 * The first model of the first provider that VERIFIED (§23.7).
 *
 * Skipping unverified providers is the no-substitution property in code: an
 * unavailable provider is never selected for a turn, so its failure cannot be
 * silently papered over by a neighbour that happens to work. Returns undefined
 * when nothing verified, which is a configured-but-unusable runtime rather than
 * an unconfigured one — `requireService` tells those apart.
 */
function firstAvailableModel(
  rt: ModelRuntime,
  config: RuntimeConfig,
  verified: readonly ProviderAvailability[],
): PiModel | undefined {
  const usable = new Set(verified.filter((e) => e.available).map((e) => e.id));
  for (const provider of config.providers) {
    if (!usable.has(provider.id)) continue;
    for (const model of provider.models) {
      const resolved = rt.getModel(provider.id, model.id);
      if (resolved) return resolved;
    }
  }
  return undefined;
}

/** Read `runtime.configure`'s payload, including §23.2's `serve`-scoped keys. */
function readRuntimeConfig(params: { [k: string]: JsonValue }): RuntimeConfig {
  const base = params as unknown as RuntimeConfig;
  const raw = params.runtime_keys;
  if (raw === null || typeof raw !== "object" || Array.isArray(raw)) return base;
  const keys: Record<string, string> = {};
  for (const [id, value] of Object.entries(raw)) {
    if (typeof value === "string") keys[id] = value;
  }
  return { ...base, runtimeKeys: keys };
}

peer.on("runtime.configure", async (params) => {
  const config = readRuntimeConfig(params);
  const configured = await createModelRuntime(config, { agentDir });
  runtime = configured.runtime;
  availability = configured.providers;
  const model = firstAvailableModel(runtime, config, availability);
  // A runtime with NO usable provider still comes up. That is §23.7's whole
  // point: the sidecar has to exist for the credential routes to relay to, and
  // a serve that refuses to start because a provider is unauthenticated is a
  // serve in which the login that would fix it is unreachable.
  service =
    model === undefined ? undefined : new SessionService({ runtime, agentDir, model, customTools });
  const usable = availability.filter((entry) => entry.available).length;
  log(`configured runtime: ${usable}/${config.providers.length} provider(s) verified`);
  return {
    ok: true,
    providers: availability.map((entry) => ({
      id: entry.id,
      available: entry.available,
      ...(entry.unavailable_reason !== undefined
        ? { unavailable_reason: entry.unavailable_reason }
        : {}),
    })),
  };
});

// ── credentials (§23.6, §23.14 items 3 and 4) ───────────────────────────────
//
// Eight relays. Pi owns storage, PKCE, token exchange and refresh; this file
// owns turning its callback conversation into request/response state. Nothing
// below returns a key, an access token, or a refresh token — `listCredentials`
// answers `CredentialInfo` (provider id + type) by Pi's own contract, which is
// the same discipline §23.8's read side follows.

/**
 * A flow projection as wire JSON, field by field.
 *
 * Written out rather than spread so the set of things that can cross this
 * boundary is visible in one place: five non-secret values and a named code.
 * A spread would silently carry any field a future `FlowProjection` gained,
 * which is exactly how a secret gets onto a wire nobody meant to widen.
 */
function wireFlow(flow: FlowProjection): { [k: string]: JsonValue } {
  const out: { [k: string]: JsonValue } = {
    provider_id: flow.provider_id,
    type: flow.type,
    state: flow.state,
  };
  if (flow.user_code !== undefined) out.user_code = flow.user_code;
  if (flow.verification_uri !== undefined) out.verification_uri = flow.verification_uri;
  if (flow.interval_seconds !== undefined) out.interval_seconds = flow.interval_seconds;
  if (flow.authorize_url !== undefined) out.authorize_url = flow.authorize_url;
  if (flow.expires_at !== undefined) out.expires_at = flow.expires_at;
  if (flow.code !== undefined) out.code = flow.code;
  return out;
}

function credentialFailure(err: unknown, providerId: string): RpcError {
  // Reduced to `{code, http_status}` before anything logs it (§23.6). The
  // original error — which may quote a token-endpoint response body — is not
  // carried, not logged, and not attached as `data.message`.
  const reduced = err instanceof CredentialError ? err : reduceLoginError(err, providerId);
  return new RpcError(ErrorCode.INVALID_REQUEST, reduced.code, {
    code: reduced.code,
    http_status: reduced.httpStatus,
    provider_id: providerId,
  });
}

peer.on("providers.list", () => {
  const rt = requireRuntime();
  return {
    catalog: rt.getProviders().map((provider) => ({
      id: provider.id,
      name: provider.name ?? provider.id,
      models: rt.getModels(provider.id).map((model) => model.id),
    })),
    verified: availability.map((entry) => ({
      id: entry.id,
      available: entry.available,
      ...(entry.unavailable_reason !== undefined
        ? { unavailable_reason: entry.unavailable_reason }
        : {}),
    })),
  };
});

peer.on("credentials.status", async (params) => {
  const rt = requireRuntime();
  const providerId = String(params.provider_id);
  // `getProviderAuthStatus` is the AUTHORITY for axis 1, and the distinction is
  // load-bearing: `listCredentials()` reports a runtime (in-memory) key and a
  // stored one identically, so reading axis 1 off it would tell an operator a
  // `serve`-scoped key was saved to their project. §23.8's axis 1 answers "what
  // would I have to change to change this?" — and "restart the server" and
  // "edit auth.json" are different answers.
  const status = rt.getProviderAuthStatus(providerId);
  const stored = await rt.listCredentials();
  const record = stored.find((info) => info.providerId === providerId);
  const flow = logins.status(providerId);
  // AXIS 2 (§23.8), and it is a memory rather than a measurement: this reports
  // what the last real turn observed, and asks the provider nothing.
  const observed = lastObserved(providerId);
  return {
    health: observed?.health ?? "unused",
    last_observed_at: observed?.at ?? null,
    provider_id: providerId,
    // Axis 1 (§23.8): `stored` is Pi's app-owned auth.json; `runtime` is this
    // process's heap; `environment` is an allowlisted variable.
    state: sourceOf(status.source),
    // The credential's TYPE, which is all Pi's own read side exposes
    // (`CredentialInfo`, never `Credential`) and all §23.8 asks for. There is
    // deliberately no `configured` boolean on this wire: a registered provider
    // carries a placeholder key, so that flag reads `true` for a provider with
    // no credential at all — a third axis that would contradict the two.
    ...(record !== undefined ? { type: record.type } : {}),
    ...(flow !== undefined ? { flow: wireFlow(flow) } : {}),
  };
});

peer.on("credentials.set_key", async (params) => {
  const rt = requireRuntime();
  const providerId = String(params.provider_id);
  const key = String(params.key);
  const scope = String(params.scope);
  if (rt.getProvider(providerId) === undefined) {
    throw credentialFailure(new CredentialError("provider_unknown", 404, providerId), providerId);
  }
  // §23.9: "the response names the state it replaced (`{"replaced":"project"}`),
  // so a rotation that landed in a different scope than intended is visible in
  // the response rather than discovered three weeks later." Read from the AUTH
  // STATUS rather than from `listCredentials`, which cannot tell a runtime key
  // from a stored one — the whole point of the field is which scope moved.
  const replaced = sourceOf(rt.getProviderAuthStatus(providerId).source);
  try {
    if (scope === "project") {
      // Pi's AuthStorage: 0600 under a proper-lockfile cross-process lock.
      await rt.login(providerId, "api_key", {
        notify: () => {},
        prompt: () => Promise.resolve(key),
      });
    } else {
      await rt.setRuntimeApiKey(providerId, key);
    }
  } catch (err) {
    throw credentialFailure(err, providerId);
  }
  // §23.9: rotation has no verb — rotating is signing in over an existing one,
  // and the response names the state it replaced so a rotation that landed in a
  // different scope than intended is visible now rather than in three weeks.
  return { ok: true, provider_id: providerId, scope, replaced };
});

peer.on("credentials.signout", async (params) => {
  const rt = requireRuntime();
  const providerId = String(params.provider_id);
  try {
    await rt.removeRuntimeApiKey(providerId);
  } catch {
    // No runtime key to remove is not a failure: sign-out is a state, and
    // reaching it from a state that already holds is idempotent.
  }
  try {
    await rt.logout(providerId);
  } catch (err) {
    throw credentialFailure(err, providerId);
  }
  await logins.cancel(providerId);
  // The provider SPEC is untouched (§23.9): the row stays, in state `none`.
  return { ok: true, provider_id: providerId, state: "none" };
});

peer.on("login.begin", async (params) => {
  const rt = requireRuntime();
  const providerId = String(params.provider_id);
  const type = String(params.type);
  if (type !== "device_code" && type !== "authorize_url") {
    throw credentialFailure(
      new CredentialError("unsupported_auth_type", 422, providerId),
      providerId,
    );
  }
  try {
    return { ok: true, ...wireFlow(await logins.begin(rt, providerId, type)) };
  } catch (err) {
    throw credentialFailure(err, providerId);
  }
});

peer.on("login.status", (params) => {
  const providerId = String(params.provider_id);
  const flow = logins.status(providerId);
  return flow === undefined ? { ok: true, flow: null } : { ok: true, flow: wireFlow(flow) };
});

peer.on("login.complete", async (params) => {
  const providerId = String(params.provider_id);
  try {
    return { ok: true, ...wireFlow(await logins.complete(providerId, String(params.input ?? ""))) };
  } catch (err) {
    throw credentialFailure(err, providerId);
  }
});

peer.on("login.cancel", async (params) => {
  const providerId = String(params.provider_id);
  const flow = await logins.cancel(providerId);
  return { ok: true, flow: flow === undefined ? null : wireFlow(flow) };
});

/** Pi's `AuthStatus.source` mapped onto §23.8's closed axis-1 vocabulary. */
function sourceOf(source: string | undefined): string {
  if (source === "stored") return "project";
  if (source === "runtime") return "serve";
  if (source === "environment") return "env";
  return "none";
}

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
  // INTERFACE.md §7A.4 / §19.22 — the workspace's composed context block.
  //
  // It arrives as its OWN parameter and is prepended as its own user-role
  // content block; it is never concatenated into `prompt` on the Python side,
  // because `BridgeRuntime.prompt` binds `prompt` as the request every
  // VALIDATION.md §4/§5 rung judges against. Absent on every turn that carries
  // no workspace context, including every `heph agent` turn.
  const contextBlock =
    params.context === undefined || params.context === null ? undefined : String(params.context);
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
      // With a context block the turn is sent as a content ARRAY whose leading
      // block is the workspace context and whose second block is the operator's
      // text verbatim (INTERFACE.md §7A.4).
      //
      // DEVIATION, reported rather than glossed: **Pi admits no genuinely
      // separate second user-role text block.** `AgentSession.sendUserMessage`
      // joins a content array's text parts with "\n" and calls `prompt()` with
      // `expandPromptTemplates: false` — so what the model receives is one user
      // message whose first paragraphs are the block. The invariant §7A.4
      // actually protects is on the Python side and is unaffected: the block
      // never reaches `bind_run_request_text`, so `prompt_number_diff` still
      // diffs the operator's own words. The second-order consequence is
      // recorded here: a turn WITH context skips file-template expansion, one
      // WITHOUT keeps it. That is the safer asymmetry — with a block prepended
      // the operator's text is no longer at message start, so template
      // expansion would fire on the workspace's own prose rather than on
      // theirs — and it changes nothing for `heph agent`, which sends no block.
      prompt: (text) =>
        contextBlock === undefined
          ? managed.session.prompt(text)
          : managed.session.sendUserMessage([
              { type: "text", text: contextBlock },
              { type: "text", text },
            ]),
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
    // §23.8/§23.10: the turn is the observation. A run that reached the provider
    // and failed on auth flips that provider's health to `rejected`; one that
    // completed flips it to `accepted`. Nothing else in this process writes it,
    // which is what makes "there is no background probe" true.
    observeTurn(managed.model.provider, state === "completed" ? undefined : errorMessage);
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
