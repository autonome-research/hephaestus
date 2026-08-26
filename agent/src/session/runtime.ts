// App-owned Pi ModelRuntime + the scripted FakeModel provider used by tests.
//
// The supervisor sends `runtime.configure {providers, credentials}` exactly once
// at start-up. This module turns that payload into a Pi `ModelRuntime` whose
// providers are: anthropic (anthropic-messages), openai-compatible (an arbitrary
// baseURL over openai-completions), and local endpoints (also openai-completions
// against a loopback baseURL). Credentials are injected ONLY from the explicit
// allowlist carried in the payload — this module never scans `process.env`, so a
// hostile ambient provider key cannot reach a session (arch §4.1, §7.2; the
// isolation test proves it).
//
// A fourth kind, `pi_native`, names a provider from Pi's *built-in* catalog
// (e.g. `openai-codex`) and is NOT registered here at all: its credential is
// whatever the app-owned `auth.json` holds, which the supervisor populates only
// when the provider config explicitly declares an `auth_source`. With no
// auth_source there is no auth.json content, so a pi_native provider simply
// fails configuration — it can never fall back to an ambient login.
//
// FakeModel is an in-process OpenAI-compatible server driven by a scripted turn
// list. It exercises the exact public provider surface (`registerProvider` with
// `api:"openai-completions"` + baseURL), the same path proven in
// spikes/agent_runtime/pi_session_proof.mjs, so lifecycle tests never touch the
// network or a real model.

import http from "node:http";
import path from "node:path";
import { registerBunOAuthFlows } from "@earendil-works/pi-ai/bun-oauth";
import { ModelRuntime } from "@earendil-works/pi-coding-agent";

// pi-ai loads OAuth flow modules (openai-codex, anthropic, ...) through a
// *variable-specifier* dynamic import that bundlers cannot follow — inside the
// esbuild-bundled sidecar that import cannot resolve at runtime, so every
// pi_native OAuth turn died in ~2 ms with "OAuth auth derivation failed"
// (2026-08-02: 15 zero-event live runs; tsc output was unaffected, and
// FakeModel providers need no OAuth flow, which is why every test stayed
// green). Pi's own standalone binary solves this with static registration;
// the sidecar is exactly that case. Idempotent, and a no-op for keyed
// providers.
registerBunOAuthFlows();

// ── configure payload ────────────────────────────────────────────────────────

export type ProviderKind = "anthropic" | "openai_compatible" | "local" | "pi_native";

export interface ProviderModelSpec {
  readonly id: string;
  readonly name: string;
  readonly contextWindow: number;
  readonly maxTokens: number;
  readonly input?: readonly ("text" | "image")[];
  readonly reasoning?: boolean;
}

/** For pi_native only the id is meaningful — the rest comes from Pi's catalog. */
export interface PiNativeModelSpec {
  readonly id: string;
}

/** A provider the app defines end-to-end: endpoint + api + explicit key. */
export interface KeyedProviderSpec {
  readonly id: string;
  readonly kind: "anthropic" | "openai_compatible" | "local";
  readonly name?: string;
  /** Required for openai_compatible/local; ignored for anthropic. */
  readonly baseUrl?: string;
  /** Key into the credential allowlist; omitted providers get no key. */
  readonly credential?: string;
  readonly models: readonly ProviderModelSpec[];
}

/**
 * A provider taken *as-is* from Pi's built-in catalog, authenticated by the
 * credential stored in the app-owned `auth.json` (typically an OAuth record the
 * supervisor exposed by symlinking a Pi auth file into the agent dir).
 *
 * Deliberately has no `credential`/`baseUrl`/`api`: nothing about the endpoint
 * or the key is app-supplied, so there is no explicit-key path to confuse with
 * it and no way for it to smuggle an ambient env var in. If `auth.json` carries
 * no record for the provider, configuration fails loudly (see
 * `RuntimeConfigError` code `provider_not_authenticated`).
 */
export interface PiNativeProviderSpec {
  readonly id: string;
  readonly kind: "pi_native";
  readonly models: readonly PiNativeModelSpec[];
}

export type ProviderSpec = KeyedProviderSpec | PiNativeProviderSpec;

/** Why a `runtime.configure` payload could not be turned into a ModelRuntime. */
export type RuntimeConfigErrorCode =
  | "credential_not_allowlisted"
  | "provider_unknown"
  | "provider_not_authenticated"
  | "model_unknown";

export class RuntimeConfigError extends Error {
  readonly code: RuntimeConfigErrorCode;
  readonly providerId: string;

  constructor(code: RuntimeConfigErrorCode, providerId: string, message: string) {
    super(message);
    this.name = "RuntimeConfigError";
    this.code = code;
    this.providerId = providerId;
  }
}

export interface RuntimeConfig {
  readonly providers: readonly ProviderSpec[];
  /** The ONLY credential source. Supervisor pre-filters to approved vars. */
  readonly credentials?: Readonly<Record<string, string>>;
}

export interface RuntimePaths {
  /** App-owned agent dir; auth.json / models-store.json live beneath it. */
  readonly agentDir: string;
}

/** A resolved, non-undefined Pi model (no transitive pi-ai import needed). */
export type PiModel = NonNullable<ReturnType<ModelRuntime["getModel"]>>;

const ZERO_COST = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } as const;

function apiForKind(kind: KeyedProviderSpec["kind"]): string {
  return kind === "anthropic" ? "anthropic-messages" : "openai-completions";
}

/**
 * Build the app-owned ModelRuntime from a configure payload. Network model
 * discovery is disabled; only the providers explicitly listed are registered.
 * Throws if a provider references a credential absent from the allowlist.
 */
export async function createModelRuntime(
  config: RuntimeConfig,
  paths: RuntimePaths,
): Promise<ModelRuntime> {
  const runtime = await ModelRuntime.create({
    authPath: path.join(paths.agentDir, "auth.json"),
    modelsPath: null,
    modelsStorePath: path.join(paths.agentDir, "models-store.json"),
    allowModelNetwork: false,
  });
  const credentials = config.credentials ?? {};
  for (const provider of config.providers) {
    if (provider.kind === "pi_native") {
      // No registerProvider: the provider *is* Pi's built-in one, and its
      // credential comes from authPath (auth.json under the agent dir).
      verifyPiNativeProvider(runtime, provider);
      continue;
    }
    let apiKey = "app-managed-no-network";
    if (provider.credential !== undefined) {
      const secret = credentials[provider.credential];
      if (secret === undefined) {
        throw new RuntimeConfigError(
          "credential_not_allowlisted",
          provider.id,
          `provider '${provider.id}' references credential '${provider.credential}' ` +
            `which is not in the allowlist`,
        );
      }
      apiKey = secret;
    }
    registerProvider(runtime, provider, apiKey);
  }
  return runtime;
}

/**
 * Check that a pi_native provider is real, authenticated, and declares models
 * Pi knows — before any session is created, so failures name the cause instead
 * of surfacing as an opaque 401 mid-run.
 */
function verifyPiNativeProvider(runtime: ModelRuntime, provider: PiNativeProviderSpec): void {
  if (runtime.getProvider(provider.id) === undefined) {
    const known = runtime
      .getProviders()
      .map((p) => p.id)
      .join(", ");
    throw new RuntimeConfigError(
      "provider_unknown",
      provider.id,
      `pi_native provider '${provider.id}' is not in Pi's built-in catalog ` +
        `(known providers: ${known})`,
    );
  }
  if (!runtime.hasConfiguredAuth(provider.id)) {
    const status = runtime.getProviderAuthStatus(provider.id);
    throw new RuntimeConfigError(
      "provider_not_authenticated",
      provider.id,
      `pi_native provider '${provider.id}' has no stored credential in the ` +
        `app-owned auth.json (auth status: ${JSON.stringify(status)}). Declare an ` +
        `'auth_source' in the provider config so the supervisor links an existing ` +
        `Pi auth.json into the agent dir, or log in for this provider.`,
    );
  }
  for (const model of provider.models) {
    if (runtime.getModel(provider.id, model.id) === undefined) {
      const available = runtime
        .getModels(provider.id)
        .map((m) => m.id)
        .join(", ");
      throw new RuntimeConfigError(
        "model_unknown",
        provider.id,
        `pi_native provider '${provider.id}' does not offer model '${model.id}' ` +
          `(available: ${available})`,
      );
    }
  }
}

function registerProvider(runtime: ModelRuntime, provider: KeyedProviderSpec, apiKey: string): void {
  const models = provider.models.map((m) => ({
    id: m.id,
    name: m.name,
    reasoning: m.reasoning ?? false,
    input: [...(m.input ?? ["text"])],
    cost: { ...ZERO_COST },
    contextWindow: m.contextWindow,
    maxTokens: m.maxTokens,
  }));
  const base = { name: provider.name ?? provider.id, apiKey, api: apiForKind(provider.kind), models };
  const providerConfig =
    provider.baseUrl !== undefined ? { ...base, baseUrl: provider.baseUrl } : base;
  runtime.registerProvider(provider.id, providerConfig);
}

// ── scripted fake model (tests only) ─────────────────────────────────────────

export interface FakeTextTurn {
  readonly kind: "text";
  readonly chunks: readonly string[];
}
export interface FakeToolCallSpec {
  readonly name: string;
  readonly arguments: Record<string, unknown>;
  readonly id?: string;
}
export interface FakeToolCallsTurn {
  readonly kind: "tool_calls";
  readonly calls: readonly FakeToolCallSpec[];
}
/** Emit one chunk then hold the connection open forever (drives abort tests). */
export interface FakeStallTurn {
  readonly kind: "stall";
}
/**
 * Fail the request with an HTTP 500 whose body carries `message` — Pi records
 * the turn with stopReason "error" and resolves (the errored-turn shape the
 * transient-fault retry in session/retry.ts is tested against).
 */
export interface FakeErrorTurn {
  readonly kind: "error";
  readonly message?: string;
  /** HTTP status of the fault (default 500; e.g. 400 for a non-transient one). */
  readonly status?: number;
}
export type FakeTurn = FakeTextTurn | FakeToolCallsTurn | FakeStallTurn | FakeErrorTurn;

export interface FakeRequestInfo {
  readonly index: number;
  readonly roles: readonly string[];
  readonly toolNames: readonly string[];
  readonly hasToolResult: boolean;
  readonly bodyText: string;
}

export type FakeTurnResolver = FakeTurn | ((req: FakeRequestInfo) => FakeTurn);

export interface FakeModelOptions {
  readonly providerId?: string;
  readonly modelId?: string;
  readonly contextWindow?: number;
  readonly maxTokens?: number;
  /** Response for tool-less requests (compaction/summarization). */
  readonly summarize?: (req: FakeRequestInfo) => string;
}

function sseChunk(model: string, delta: unknown, finish: string | null): string {
  const payload = {
    id: "chatcmpl-heph-fake",
    object: "chat.completion.chunk",
    created: Math.floor(Date.now() / 1000),
    model,
    choices: [{ index: 0, delta, finish_reason: finish }],
    ...(finish ? { usage: { prompt_tokens: 8, completion_tokens: 4, total_tokens: 12 } } : {}),
  };
  return `data: ${JSON.stringify(payload)}\n\n`;
}

/**
 * In-process OpenAI-compatible model server. Each tool-enabled request consumes
 * the next scripted turn; tool-less requests (compaction) are answered by
 * `summarize` and never advance the script. When the script is exhausted the
 * server returns a terminal text turn so the agent loop always settles.
 */
export class FakeModel {
  readonly providerId: string;
  readonly modelId: string;
  readonly port: number;
  readonly baseUrl: string;
  private readonly server: http.Server;
  private readonly requestLog: FakeRequestInfo[] = [];
  private script: FakeTurnResolver[];
  private cursor = 0;
  private readonly contextWindow: number;
  private readonly maxTokens: number;
  private readonly summarize: (req: FakeRequestInfo) => string;

  private constructor(server: http.Server, port: number, script: FakeTurnResolver[], opts: FakeModelOptions) {
    this.server = server;
    this.port = port;
    this.providerId = opts.providerId ?? "heph-fake";
    this.modelId = opts.modelId ?? "heph-fake-model";
    this.baseUrl = `http://127.0.0.1:${port}/v1`;
    this.contextWindow = opts.contextWindow ?? 128000;
    this.maxTokens = opts.maxTokens ?? 4096;
    this.summarize = opts.summarize ?? ((req) => summarizeDefault(req));
    this.script = script;
  }

  static async start(script: readonly FakeTurnResolver[], opts: FakeModelOptions = {}): Promise<FakeModel> {
    const holder: { model?: FakeModel } = {};
    const server = http.createServer((req, res) => {
      holder.model?.handle(req, res);
    });
    const port = await new Promise<number>((resolve) => {
      server.listen(0, "127.0.0.1", () => {
        const addr = server.address();
        resolve(typeof addr === "object" && addr ? addr.port : 0);
      });
    });
    const model = new FakeModel(server, port, [...script], opts);
    holder.model = model;
    return model;
  }

  get requests(): readonly FakeRequestInfo[] {
    return this.requestLog;
  }

  /** Replace the remaining script (resets the cursor). */
  setScript(script: readonly FakeTurnResolver[]): void {
    this.script = [...script];
    this.cursor = 0;
  }

  /** ProviderSpec for createModelRuntime; the fake needs no real credential. */
  providerSpec(): ProviderSpec {
    return {
      id: this.providerId,
      kind: "openai_compatible",
      name: "Hephaestus Fake Provider",
      baseUrl: this.baseUrl,
      models: [
        { id: this.modelId, name: "Heph Fake Model", contextWindow: this.contextWindow, maxTokens: this.maxTokens },
      ],
    };
  }

  async close(): Promise<void> {
    this.server.closeAllConnections();
    await new Promise<void>((resolve) => this.server.close(() => resolve()));
  }

  private handle(req: http.IncomingMessage, res: http.ServerResponse): void {
    let body = "";
    req.on("data", (d: Buffer) => (body += d.toString("utf8")));
    req.on("end", () => {
      const parsed = parseBody(body);
      const info: FakeRequestInfo = {
        index: this.requestLog.length,
        roles: parsed.messages.map((m) => m.role),
        toolNames: parsed.tools.map((t) => t.name),
        hasToolResult: parsed.messages.some((m) => m.role === "tool"),
        bodyText: body,
      };
      this.requestLog.push(info);

      // Tool-less request => compaction/summarization: answer, do not advance.
      if (info.toolNames.length === 0) {
        res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
        this.writeText(res, this.summarize(info));
        return;
      }
      const turn = this.nextTurn(info);
      if (turn.kind === "error") {
        // The scripted provider fault: an HTTP 500 whose body message is what
        // Pi surfaces as the errored turn's errorMessage.
        res.writeHead(turn.status ?? 500, { "content-type": "application/json" });
        res.end(
          JSON.stringify({
            error: { message: turn.message ?? "fake provider fault", type: "server_error" },
          }),
        );
        return;
      }
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache" });
      if (turn.kind === "stall") {
        res.write(sseChunk(this.modelId, { role: "assistant", content: "thinking..." }, null));
        // Intentionally never end: the caller aborts.
        return;
      }
      if (turn.kind === "tool_calls") {
        this.writeToolCalls(res, turn.calls);
        return;
      }
      this.writeText(res, turn.chunks);
    });
  }

  private nextTurn(info: FakeRequestInfo): FakeTurn {
    const resolver = this.script[this.cursor];
    if (resolver === undefined) {
      return { kind: "text", chunks: ["HEPH_DONE"] };
    }
    this.cursor += 1;
    return typeof resolver === "function" ? resolver(info) : resolver;
  }

  private writeText(res: http.ServerResponse, chunks: string | readonly string[]): void {
    const parts = typeof chunks === "string" ? [chunks] : chunks;
    res.write(sseChunk(this.modelId, { role: "assistant", content: "" }, null));
    for (const part of parts) res.write(sseChunk(this.modelId, { content: part }, null));
    res.write(sseChunk(this.modelId, {}, "stop"));
    res.write("data: [DONE]\n\n");
    res.end();
  }

  private writeToolCalls(res: http.ServerResponse, calls: readonly FakeToolCallSpec[]): void {
    res.write(sseChunk(this.modelId, { role: "assistant", content: "" }, null));
    const tool_calls = calls.map((call, index) => ({
      index,
      id: call.id ?? `call_${index}`,
      type: "function",
      function: { name: call.name, arguments: JSON.stringify(call.arguments) },
    }));
    res.write(sseChunk(this.modelId, { tool_calls }, null));
    res.write(sseChunk(this.modelId, {}, "tool_calls"));
    res.write("data: [DONE]\n\n");
    res.end();
  }
}

interface ParsedBody {
  messages: { role: string }[];
  tools: { name: string }[];
}

function parseBody(body: string): ParsedBody {
  let raw: unknown;
  try {
    raw = JSON.parse(body || "{}");
  } catch {
    raw = {};
  }
  const obj = (raw ?? {}) as { messages?: unknown; tools?: unknown };
  const messages = Array.isArray(obj.messages)
    ? obj.messages.map((m) => ({ role: String((m as { role?: unknown }).role ?? "") }))
    : [];
  const tools = Array.isArray(obj.tools)
    ? obj.tools.map((t) => ({
        name: String((t as { function?: { name?: unknown } }).function?.name ?? ""),
      }))
    : [];
  return { messages, tools };
}

const PINNED_MARKER_OPEN = "<<HEPHAESTUS_PINNED_SUMMARY>>";

function summarizeDefault(req: FakeRequestInfo): string {
  // If a pinned CAD summary was handed to compaction, echo it verbatim so the
  // post-compaction transcript still carries it.
  const start = req.bodyText.indexOf(PINNED_MARKER_OPEN);
  if (start >= 0) {
    return req.bodyText.slice(start, start + 4096);
  }
  return "COMPACTED: session summarized.";
}
